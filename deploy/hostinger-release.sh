#!/bin/bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077

base=/opt/garrison-portal
state="$base/deploy"
repository=nirzaf/garrison-investments
portal=https://portal.garrisons.lk
project=garrison-portal
frontend_volume=garrison-portal_frontend_dist
verifier=/usr/local/libexec/garrison-release-contract.py

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

report_duration() {
  printf '%s took %ss\n' "$1" "$((SECONDS - $2))"
}

[[ $# == 4 && "$1" =~ ^[0-9]+$ && "$2" =~ ^[0-9a-f]{40}$ &&
   "$3" == rollback-v2 && "$4" == release-contract-v1 ]] ||
  die 'Expected a CI run ID, full SHA, rollback-v2 and release-contract-v1.'
run_id=$1
sha=$2
IFS= read -r token || die 'A GitHub Actions token is required on stdin.'
[[ "$token" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'Invalid GitHub Actions token format.'
IFS= read -r deploy_run_id || die 'A deployment workflow run ID is required on stdin.'
[[ "$deploy_run_id" =~ ^[1-9][0-9]*$ ]] || die 'Invalid deployment workflow run ID.'
IFS= read -r deploy_attempt || die 'A deployment workflow attempt is required on stdin.'
[[ "$deploy_attempt" =~ ^[1-9][0-9]*$ ]] || die 'Invalid deployment workflow attempt.'

exec 9>"$state/deploy.lock"
flock -w 60 9 || die 'Another production deployment is running.'

github() {
  printf 'header = "Authorization: Bearer %s"\n' "$token" |
    curl --config - --fail --silent --show-error --location --retry 2 --max-time 90 \
      "https://api.github.com/repos/$repository/$1"
}

verify_main() {
  github git/ref/heads/main | python3 -c '
import json, sys
if json.load(sys.stdin)["object"]["sha"] != sys.argv[1]:
    sys.exit("The candidate is no longer the tip of main.")
' "$sha"
}

verify_authorization() {
  local component mode
  [[ $EUID == 0 && -f "$verifier" ]] ||
    die 'The root-installed release verifier is unavailable.'
  for component in / /usr /usr/local /usr/local/libexec "$verifier"; do
    [[ ! -L "$component" && -O "$component" ]] ||
      die 'The release verifier path must be root-owned and free of symlinks.'
    mode=$(stat -c '%a' "$component")
    (( (8#$mode & 022) == 0 )) ||
      die 'The release verifier must be protected from runner writes.'
  done
  printf '%s\n' "$token" | /usr/bin/python3 -I "$verifier" \
    --host-state "$state" --commit "$sha" --ci-run "$run_id" --deploy-run "$deploy_run_id" \
    --deploy-attempt "$deploy_attempt" "$@"
}

github "actions/runs/$run_id" | python3 -c '
import json, sys
r = json.load(sys.stdin)
if not (
    r["path"] == ".github/workflows/ci.yml"
    and r["event"] == "push"
    and r["status"] == "completed"
    and r["conclusion"] == "success"
    and r["head_branch"] == "main"
    and r["head_repository"]["full_name"] == sys.argv[1]
    and r["head_sha"] == sys.argv[2]
):
    sys.exit("The candidate does not match a successful CI push to main.")
' "$repository" "$sha"
verify_main

previous=$(readlink -f "$state/current")
[[ "$previous" == "$base/releases/"* && -f "$previous/.env" ]] ||
  die 'The active production release has not been initialized.'
if [[ "$(cat "$previous/SOURCE_COMMIT")" == "$sha" ]]; then
  curl --fail --silent --show-error --max-time 10 "$portal/health/readiness"
  printf '\nCommit %s is already deployed.\n' "$sha"
  exit 0
fi

phase_started=$SECONDS
authorization=$(verify_authorization)
candidate=$(mktemp -d "$base/releases/$sha.XXXXXX")
github "tarball/$sha" | (umask 022; tar -xzf - --strip-components=1 --no-same-owner --no-same-permissions -C "$candidate")
for reserved in .env .images.env SOURCE_COMMIT DEPLOYED ACTIVATION_FAILED PREDEPLOY.json READINESS.json; do
  [[ ! -e "$candidate/$reserved" && ! -L "$candidate/$reserved" ]] ||
    die 'The source archive contains a reserved release file.'
done
install -m 0600 "$state/production.env" "$candidate/.env"
printf '%s\n' "$sha" > "$candidate/SOURCE_COMMIT"
report_duration 'Release authorization and source preparation' "$phase_started"

generation=$(cat "$candidate/deploy/rollback-generation")
[[ "$generation" =~ ^[1-9][0-9]*$ ]] || die 'Invalid candidate rollback generation.'
previous_generation=
if [[ -f "$previous/deploy/rollback-generation" ]]; then
  previous_generation=$(cat "$previous/deploy/rollback-generation")
fi

same_backend_runtime() (
  shopt -s dotglob nullglob
  local entry name counterpart
  [[ -d "$1" && -d "$2" ]] || return 1
  for entry in "$1"/*; do
    name=${entry##*/}
    case "$name" in ARCHITECTURE.md|tests) continue ;; esac
    counterpart="$2/$name"
    [[ ( -d "$entry" && -d "$counterpart" ) || ( ! -d "$entry" && ! -d "$counterpart" ) ]] ||
      return 1
    diff -qr --exclude=tests -- "$entry" "$counterpart" >/dev/null || return 1
  done
  for entry in "$2"/*; do
    name=${entry##*/}
    case "$name" in ARCHITECTURE.md|tests) continue ;; esac
    [[ -e "$1/$name" || -L "$1/$name" ]] || return 1
  done
)

runtime_changed=0
if [[ "$generation" != "$previous_generation" ]] ||
   ! same_backend_runtime "$previous/backend" "$candidate/backend" ||
   ! cmp -s "$previous/docker-compose.prod.yml" "$candidate/docker-compose.prod.yml" ||
   ! diff -qr --exclude=ssl "$previous/nginx" "$candidate/nginx" >/dev/null ||
   ! diff -qr "$previous/observability" "$candidate/observability" >/dev/null; then
  runtime_changed=1
fi

frontend_image="garrison-portal-release-frontend:$sha"
if (( runtime_changed )); then
  backend_image="garrison-portal-release-backend:$sha"
else
  backend_image=$(docker inspect --format '{{.Config.Image}}' "$project-backend-1")
fi
printf '\nGARRISON_FRONTEND_IMAGE=%s\nGARRISON_BACKEND_IMAGE=%s\n' \
  "$frontend_image" "$backend_image" > "$candidate/.images.env"

compose() {
  local directory=$1
  shift
  docker compose --project-name "$project" --project-directory "$directory" \
    --env-file "$directory/.env" --env-file "$directory/.images.env" \
    -f "$directory/docker-compose.prod.yml" \
    -f "$state/compose.vps.yml" "$@"
}

phase_started=$SECONDS
compose "$candidate" config --quiet
if ! docker image inspect "$frontend_image" >/dev/null 2>&1; then
  compose "$candidate" build frontend_dist
fi
image_heads() {
  docker run --rm --network none --entrypoint alembic "$1" heads |
    awk 'NF {print $1}' | sort
}

if (( runtime_changed )); then
  # These services and data resources require a separate maintenance procedure.
  python3 - "$previous" "$candidate" \
    <(compose "$previous" config --format json) <(compose "$candidate" config --format json) <<'PY'
import json
import sys

def normalize_release_paths(config, root):
    for name in ("grafana_db_init", "loki_minio_init"):
        service = config["services"][name]
        for volume in service.get("volumes", []):
            if volume["type"] == "bind":
                volume["source"] = volume["source"].removeprefix(root + "/")
        for env_file in service.get("env_file", []):
            env_file["path"] = env_file["path"].removeprefix(root + "/")

with open(sys.argv[3]) as old, open(sys.argv[4]) as new:
    before, after = json.load(old), json.load(new)
normalize_release_paths(before, sys.argv[1])
normalize_release_paths(after, sys.argv[2])
for key in ("volumes", "networks"):
    if before[key] != after[key]:
        sys.exit(f"Production {key} changed. Prepare a maintenance rollout first.")
for name in ("postgres", "redis", "minio", "grafana_db_init", "loki_minio_init"):
    if before["services"][name] != after["services"][name]:
        sys.exit(f"Production service {name} changed. Prepare a maintenance rollout first.")
PY
  for file in observability/postgres/init-grafana-db.sh observability/minio/loki-policy.json; do
    cmp -s "$previous/$file" "$candidate/$file" ||
      die 'Storage bootstrap files changed. Prepare a maintenance rollout first.'
  done
  if ! docker image inspect "$backend_image" >/dev/null 2>&1; then
    compose "$candidate" build backend
  fi
  compose "$candidate" pull --policy missing nginx grafana loki alloy
fi
report_duration 'Image preparation and configuration checks' "$phase_started"

backend_id=$(docker image inspect --format '{{.Id}}' "$backend_image")
frontend_id=$(docker image inspect --format '{{.Id}}' "$frontend_image")
printf '%s' "$authorization" | python3 -c '
import json, sys
approved = json.load(sys.stdin)["runtime_identity"]["image_digests"]
if approved != {"backend": sys.argv[1], "frontend": sys.argv[2]}:
    sys.exit("Built images differ from the authorized candidate.")
' "$backend_id" "$frontend_id"

heads=$(image_heads "$backend_image")
current=$(docker exec "$project-postgres-1" sh -ec \
  'psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version"' | sort)
[[ -n "$heads" && "$heads" == "$current" ]] ||
  die 'Pending database migrations require the reviewed maintenance procedure.'

verify_main

hash() { sha256sum | cut -d' ' -f1; }

read_frontend_identity() {
  local identity extra asset_pattern='^/assets/index-[A-Za-z0-9_-]+\.js$'
  local digest_pattern='^[a-f0-9]{64}$'
  identity=$(docker run --rm --network none "$1" sh -ec '
    cd /dist
    asset=$(grep -o "/assets/index-[^\"]*\.js" index.html)
    case "$asset" in
      /assets/index-*.js) ;;
      *) exit 1 ;;
    esac
    name=${asset#/assets/index-}
    name=${name%.js}
    case "$name" in
      ""|*[!A-Za-z0-9_-]*) exit 1 ;;
    esac
    index_hash=$(sha256sum index.html)
    asset_hash=$(sha256sum ".$asset")
    worker_hash=$(sha256sum sw.js)
    printf "%s %s %s %s\n" "${index_hash%% *}" "$asset" "${asset_hash%% *}" "${worker_hash%% *}"
  ') || die 'Unable to read the frontend entry point and hashes from the release image.'

  read -r expected asset expected_asset expected_worker extra <<< "$identity"
  [[ "$asset" =~ $asset_pattern ]] || die 'The frontend entry point is missing.'
  [[ -z "$extra" && "$identity" == "$expected $asset $expected_asset $expected_worker" &&
     "$expected" =~ $digest_pattern && "$expected_asset" =~ $digest_pattern &&
     "$expected_worker" =~ $digest_pattern ]] || die 'Invalid frontend hashes from the release image.'
}

read_frontend_identity "$frontend_image"
runtime_args=()
while IFS= read -r head; do
  runtime_args+=(--schema-head "$head")
done <<< "$current"

publish_frontend() {
  docker run --rm --network none -v "$frontend_volume:/site" "$1" sh -ec '
    for item in /dist/*; do
      [ "${item##*/}" = index.html ] || cp -a "$item" /site/
    done
    cp /dist/index.html /site/.index-next.html
    mv -f /site/.index-next.html /site/index.html
  '
}

apply_runtime() {
  compose "$1" up --detach --no-build --pull never --no-deps --wait --wait-timeout 150 \
    backend celery_worker celery_beat grafana loki alloy nginx || return
  docker exec "$project-nginx-1" nginx -s reload
}

rollback_compatible=0
if [[ "$generation" == "$previous_generation" ]]; then
  old_backend=$(sed -n 's/^GARRISON_BACKEND_IMAGE=//p' "$previous/.images.env")
  old_frontend=$(sed -n 's/^GARRISON_FRONTEND_IMAGE=//p' "$previous/.images.env")
  if [[ -n "$old_backend" && -n "$old_frontend" ]] &&
     old_heads=$(image_heads "$old_backend") && [[ "$old_heads" == "$current" ]] &&
     docker image inspect "$old_frontend" >/dev/null; then
    rollback_compatible=1
  fi
fi
runtime_attempted=0
frontend_attempted=0

rollback() {
  local result=$?
  if (( result && (runtime_attempted || frontend_attempted) )); then
    set +e
    if (( rollback_compatible )); then
      printf 'Activation failed. Restoring the previous compatible application release.\n' >&2
      if (( runtime_attempted )); then
        apply_runtime "$previous" || printf 'Application rollback failed. Check the production services.\n' >&2
      fi
      if (( frontend_attempted )); then
        publish_frontend "$old_frontend" || printf 'Frontend rollback failed. Restore the compatible static bundle.\n' >&2
      fi
    else
      printf 'Activation failed without a compatible rollback. Keep the maintenance write block in place and recover forward.\n' >&2
      printf 'Commit: %s\nCI run: %s\nUTC: %s\nExit: %s\n' \
        "$sha" "$run_id" "$(date -u +%FT%TZ)" "$result" > "$candidate/ACTIVATION_FAILED"
      compose "$candidate" stop nginx celery_beat celery_worker backend ||
        printf 'Automatic containment failed. Stop portal ingress and writers from the host.\n' >&2
    fi
  fi
  exit "$result"
}

trap rollback EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if (( runtime_changed )); then
  phase_started=$SECONDS
  compose "$candidate" run --rm --no-deps --pull never -T backend \
    python scripts/backup.py --target all --skip-retention
  report_duration 'Pre-activation backup' "$phase_started"
fi
verify_main
verify_authorization "${runtime_args[@]}" --backend-image "$backend_id" --frontend-image "$frontend_id" \
  --frontend-sha256 "$expected_asset" --service-worker-sha256 "$expected_worker" > "$candidate/PREDEPLOY.json"
unset token
phase_started=$SECONDS
if (( runtime_changed )); then
  runtime_attempted=1
  apply_runtime "$candidate"
fi
frontend_attempted=1
publish_frontend "$frontend_image"
report_duration 'Activation' "$phase_started"

phase_started=$SECONDS
for service in backend celery_worker celery_beat; do
  container=$(compose "$candidate" ps -q "$service")
  [[ -n "$container" && "$(docker inspect --format '{{.Image}}' "$container")" == "$backend_id" ]] ||
    die "The active $service image differs from the approved backend build."
done
actual=$(curl --fail --silent --show-error --retry 4 --max-time 12 "$portal/login" | hash)
[[ "$expected" == "$actual" ]] || die 'The served sign-in page differs from the release image.'
actual_asset=$(curl --fail --silent --show-error --retry 4 --max-time 12 "$portal$asset" | hash)
[[ "$expected_asset" == "$actual_asset" ]] || die 'The served JavaScript differs from the release image.'
actual_worker=$(curl --fail --silent --show-error --retry 4 --max-time 12 "$portal/sw.js" | hash)
[[ "$expected_worker" == "$actual_worker" ]] || die 'The served service worker differs from the release image.'
curl --fail --silent --show-error --retry 4 --max-time 12 "$portal/health/readiness" > "$candidate/READINESS.json"
python3 - "$candidate/READINESS.json" <<'PY'
import json
import sys

with open(sys.argv[1]) as file:
    if json.load(file) != {"status": "ready", "database": "connected"}:
        sys.exit("The served readiness response does not report a connected database.")
PY
report_duration 'Live image and readiness verification' "$phase_started"
cat "$candidate/READINESS.json"

printf 'Commit: %s\nCI run: %s\nDeploy run: %s\nDeploy attempt: %s\nUTC: %s\nFrontend asset: %s\nAsset SHA-256: %s\nService worker SHA-256: %s\nBackend image: %s\nFrontend image: %s\nSchema heads: %s\n' \
  "$sha" "$run_id" "$deploy_run_id" "$deploy_attempt" "$(date -u +%FT%TZ)" \
  "$asset" "$expected_asset" "$expected_worker" \
  "$backend_id" "$frontend_id" "$(tr '\n' ' ' <<< "$current")" > "$candidate/DEPLOYED"
ln -sfn "$candidate" "$state/.current-next"
mv -Tf "$state/.current-next" "$state/current"
trap - EXIT INT TERM
printf '\nDeployed %s from CI run %s. Frontend asset %s verified.\n' "$sha" "$run_id" "$asset"
