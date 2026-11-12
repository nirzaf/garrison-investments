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

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

[[ $# == 3 && "$1" =~ ^[0-9]+$ && "$2" =~ ^[0-9a-f]{40}$ && "$3" == rollback-v2 ]] ||
  die 'Expected a GitHub CI run ID, a full commit SHA, and the rollback-v2 protocol.'
run_id=$1
sha=$2
IFS= read -r token || die 'A GitHub Actions token is required on stdin.'
[[ "$token" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'Invalid GitHub Actions token format.'

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

candidate=$(mktemp -d "$base/releases/$sha.XXXXXX")
github "tarball/$sha" | (umask 022; tar -xzf - --strip-components=1 --no-same-owner --no-same-permissions -C "$candidate")
[[ ! -e "$candidate/.env" && ! -L "$candidate/.env" ]] ||
  die 'The source archive must not contain a production environment file.'
install -m 0600 "$state/production.env" "$candidate/.env"
printf '%s\n' "$sha" > "$candidate/SOURCE_COMMIT"

generation=$(cat "$candidate/deploy/rollback-generation")
[[ "$generation" =~ ^[1-9][0-9]*$ ]] || die 'Invalid candidate rollback generation.'
previous_generation=
if [[ -f "$previous/deploy/rollback-generation" ]]; then
  previous_generation=$(cat "$previous/deploy/rollback-generation")
fi

runtime_changed=0
if [[ "$generation" != "$previous_generation" ]] ||
   ! diff -qr --exclude=tests "$previous/backend" "$candidate/backend" >/dev/null ||
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

compose "$candidate" config --quiet
compose "$candidate" build frontend_dist
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
  compose "$candidate" build backend
  compose "$candidate" pull --policy missing nginx grafana loki alloy
fi

heads=$(image_heads "$backend_image")
current=$(docker exec "$project-postgres-1" sh -ec \
  'psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version"' | sort)
[[ -n "$heads" && "$heads" == "$current" ]] ||
  die 'Pending database migrations require the reviewed maintenance procedure.'

verify_main
unset token

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
  compose "$candidate" run --rm --no-deps --pull never -T backend \
    python scripts/backup.py --target all --skip-retention
  runtime_attempted=1
  apply_runtime "$candidate"
fi
frontend_attempted=1
publish_frontend "$frontend_image"

hash() { sha256sum | cut -d' ' -f1; }
expected=$(docker run --rm --network none "$frontend_image" cat /dist/index.html | hash)
actual=$(curl --fail --silent --show-error --retry 4 --max-time 12 "$portal/login" | hash)
[[ "$expected" == "$actual" ]] || die 'The served sign-in page differs from the release image.'
asset=$(docker run --rm --network none "$frontend_image" sh -ec 'grep -o "/assets/index-[^\"]*\.js" /dist/index.html')
[[ "$asset" =~ ^/assets/index-[A-Za-z0-9_-]+\.js$ ]] || die 'The frontend entry point is missing.'
expected_asset=$(docker run --rm --network none "$frontend_image" cat "/dist$asset" | hash)
actual_asset=$(curl --fail --silent --show-error --retry 4 --max-time 12 "$portal$asset" | hash)
[[ "$expected_asset" == "$actual_asset" ]] || die 'The served JavaScript differs from the release image.'
expected_worker=$(docker run --rm --network none "$frontend_image" cat /dist/sw.js | hash)
actual_worker=$(curl --fail --silent --show-error --retry 4 --max-time 12 "$portal/sw.js" | hash)
[[ "$expected_worker" == "$actual_worker" ]] || die 'The served service worker differs from the release image.'
curl --fail --silent --show-error --retry 4 --max-time 12 "$portal/health/readiness"

printf 'Commit: %s\nCI run: %s\nUTC: %s\nFrontend asset: %s\nAsset SHA-256: %s\nService worker SHA-256: %s\n' \
  "$sha" "$run_id" "$(date -u +%FT%TZ)" "$asset" "$expected_asset" "$expected_worker" > "$candidate/DEPLOYED"
ln -sfn "$candidate" "$state/.current-next"
mv -Tf "$state/.current-next" "$state/current"
trap - EXIT INT TERM
printf '\nDeployed %s from CI run %s. Frontend asset %s verified.\n' "$sha" "$run_id" "$asset"
