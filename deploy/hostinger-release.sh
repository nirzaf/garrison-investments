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
patched_nginx_image='nginx:1.30.7-alpine@sha256:caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3'

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

report_duration() {
  printf '%s took %ss\n' "$1" "$((SECONDS - $2))"
}

[[ $# == 4 && "$1" =~ ^[0-9]+$ && "$2" =~ ^[0-9a-f]{40}$ &&
   "$3" == rollback-v2 && ( "$4" == technical-checks-v1 || "$4" == pinned-no-backup-093 || "$4" == forward-only-093-to-097 || "$4" == incident-replacement ) ]] ||
  die 'Expected a CI run ID, full SHA, rollback-v2 and release mode.'
run_id=$1
sha=$2
release_mode=$4
expected_main=$sha
pinned=0
forward097=0
incident_replacement=0
[[ "$release_mode" != forward-only-093-to-097 ]] || forward097=1
[[ "$release_mode" != incident-replacement ]] || incident_replacement=1
if [[ "$release_mode" == pinned-no-backup-093 ]]; then
  pinned=1
  [[ "$sha" == 0d581001bd294f79a47021c7e30f75a1bf291d2a && "$run_id" == 44163196512 ]] ||
    die "Pinned exception does not match the authorized candidate and CI run."
fi
if (( incident_replacement )); then
  [[ "$sha" == 65308a2af263cd59e90276b3a771d4ed6ecbf842 && "$run_id" == 44734573582 ]] ||
    die 'Incident replacement is pinned to the previously verified green 65308a2 release.'
fi
IFS= read -r token || die 'A GitHub Actions token is required on stdin.'
[[ "$token" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'Invalid GitHub Actions token format.'
IFS= read -r deploy_run_id || die 'A deployment workflow run ID is required on stdin.'
[[ "$deploy_run_id" =~ ^[1-9][0-9]*$ ]] || die 'Invalid deployment workflow run ID.'
IFS= read -r deploy_attempt || die 'A deployment workflow attempt is required on stdin.'
[[ "$deploy_attempt" =~ ^[1-9][0-9]*$ ]] || die 'Invalid deployment workflow attempt.'

# Keep the privileged entrypoint's inputs under host operator control.
[[ $EUID == 0 ]] || die 'Production deployment must run as root.'
for directory in /opt "$base" "$state" "$base/releases"; do
  [[ -d "$directory" && ! -L "$directory" && -O "$directory" ]] ||
    die 'Production deployment directories must be root-owned and free of symlinks.'
  mode=$(stat -c '%a' "$directory")
  (( (8#$mode & 022) == 0 )) || die 'Production deployment directories must be protected from runner writes.'
done
for file in "$state/production.env" "$state/compose.vps.yml"; do
  [[ -f "$file" && ! -L "$file" && -O "$file" ]] ||
    die 'Production configuration must be root-owned and free of symlinks.'
  mode=$(stat -c '%a' "$file")
  (( (8#$mode & 022) == 0 )) || die 'Production configuration must be protected from runner writes.'
done
mode=$(stat -c '%a' "$state/production.env")
(( (8#$mode & 077) == 0 )) || die 'Production secrets must be readable only by root.'

exec 9>"$state/deploy.lock"
flock -w 60 9 || die 'Another production deployment is running.'

assert_forward_maintenance_clear() {
  local marker=$state/forward097.attempt reconciled=$state/forward097.reconciled.json
  if [[ -e "$marker" || -L "$marker" ]]; then
    [[ -f "$marker" && ! -L "$marker" ]] || die 'The original forward097 marker is unsafe.'
    verify_forward_reconcile_tool
    if (( incident_replacement )); then
      [[ ! -e "$reconciled" && ! -L "$reconciled" ]] ||
        die 'Incident already reconciled; use the normal release mode.'
      python3 "$forward_reconcile_tool" check --lock-fd 9 ||
        die 'Historical forward097 evidence failed exact reconciliation checks.'
    else
      python3 "$forward_reconcile_tool" verify --lock-fd 9 ||
        die 'A forward097 attempt requires a verified reconciliation receipt.'
    fi
  elif (( incident_replacement )); then
    die 'Incident replacement mode requires the preserved forward097.attempt marker.'
  elif [[ -e "$reconciled" || -L "$reconciled" ]]; then
    die 'A reconciliation receipt without its original marker requires operator review.'
  fi
}

forward_reconcile_tool=/usr/local/lib/garrison-release/forward097_reconcile.py
verify_forward_reconcile_tool() {
  python3 - "$forward_reconcile_tool" <<'PYRECONCILE'
import hashlib,pathlib,stat,sys
base=pathlib.Path('/usr/local/lib/garrison-release')
for path in (base.parent.parent.parent,base.parent.parent,base.parent,base):
 info=path.lstat()
 if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
  raise SystemExit('Forward reconciliation installation is not protected')
path=pathlib.Path(sys.argv[1]);info=path.lstat()
if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
 raise SystemExit('Forward reconciliation helper is not root-controlled')
if hashlib.sha256(path.read_bytes()).hexdigest()!='d800ea1543999f99bc70fc31a1c0032ee0b52e0381b74ac0597f96f104f9c9ea':
 raise SystemExit('Forward reconciliation helper bytes differ from the reviewed entrypoint')
PYRECONCILE
}
assert_forward_maintenance_clear

consume_pinned_exception() {
  local permit=$state/pinned-no-backup-093.permit consumed=$state/pinned-no-backup-093.used
  local bound_run bound_attempt bound_main start end extra now
  [[ -f "$permit" && ! -L "$permit" && -O "$permit" &&
     ! -e "$consumed" && ! -L "$consumed" && "$(stat -c '%a' "$permit")" == 600 ]] ||
    die 'Pinned exception permit is unavailable, unsafe, or already consumed.'
  read -r bound_run bound_attempt bound_main start end extra < "$permit" ||
    die 'Pinned exception permit is invalid.'
  now=$(date -u +%s)
  [[ "$bound_run" == "$deploy_run_id" && "$bound_attempt" == "$deploy_attempt" &&
     -z "$extra" && "$bound_main" =~ ^[a-f0-9]{40}$ &&
     "$start" =~ ^[1-9][0-9]{9}$ && "$end" =~ ^[1-9][0-9]{9}$ ]] &&
    (( start <= now && now < end && end - start <= 1800 )) ||
    die 'Pinned exception run, attempt or window does not match.'
  mv -T -- "$permit" "$consumed"
  pinned_end=$end
  expected_main=$bound_main
}

assert_pinned_window() {
  (( $(date -u +%s) < pinned_end )) || die 'Pinned exception window expired.'
}

github() {
  printf 'header = "Authorization: Bearer %s"\n' "$token" |
    curl --config - --fail --silent --show-error --location --retry 2 --max-time 90 \
      "https://api.github.com/repos/$repository/$1"
}

verify_no_predecessor_production_deployment() {
  local page=1 count
  while :; do
    count=$(github "deployments?sha=60be439923df92e127540ffc9f0b509879797c1b&per_page=100&page=$page" | python3 -c '
import json, sys

deployments = json.load(sys.stdin)
if not isinstance(deployments, list):
    sys.exit("GitHub deployments response is invalid.")
if any(not isinstance(item, dict) for item in deployments):
    sys.exit("GitHub deployments response contains an invalid record.")
if any(
    str(item.get("environment", "")).casefold() == "production"
    for item in deployments
):
    sys.exit("A Production deployment record exists for the predecessor; independent review is required.")
print(len(deployments))
') || return
    if (( count < 100 )); then
      return 0
    fi
    if (( page >= 100 )); then
      die 'Cannot verify every predecessor deployment record within the bounded page limit.'
    fi
    page=$((page + 1))
  done
}

verify_main() {
  github git/ref/heads/main | python3 -c '
import json, sys
if json.load(sys.stdin)["object"]["sha"] != sys.argv[1]:
    sys.exit("The candidate is no longer the tip of main.")
' "$expected_main"
}

verify_ci() {
  local attempt checked_run=${1:-$run_id} checked_sha=${2:-$sha}
  attempt=$(github "actions/runs/$checked_run" | python3 -c '
import json, sys

run = json.load(sys.stdin)
attempt = run.get("run_attempt")
if not (
    run.get("id") == int(sys.argv[1])
    and run.get("path") == ".github/workflows/ci.yml"
    and run.get("event") == "push"
    and run.get("status") == "completed"
    and run.get("conclusion") == "success"
    and run.get("head_branch") == "main"
    and (run.get("head_repository") or {}).get("full_name") == sys.argv[2]
    and run.get("head_sha") == sys.argv[3]
    and type(attempt) is int and attempt > 0
):
    sys.exit("The candidate does not match a successful CI push to main.")
print(attempt)
' "$checked_run" "$repository" "$checked_sha") || return
  github "actions/runs/$checked_run/attempts/$attempt/jobs?per_page=100" | python3 -c '
import json, sys

required = {
    "Backend lint and types", "Frontend lint, types, tests and build",
    "Compose files are valid", "Backend tests (1/2)", "Backend tests (2/2)",
    "Browser regressions (1/2)", "Browser regressions (2/2)",
}
response = json.load(sys.stdin)
jobs = response["jobs"]
names = [job.get("name") for job in jobs if job.get("name") in required]
if (
    response["total_count"] != len(jobs)
    or set(names) != required
    or len(names) != len(required)
    or any(
        job.get("run_id") != int(sys.argv[1])
        or job.get("head_sha") != sys.argv[2]
        or job.get("run_attempt") != int(sys.argv[3])
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
        for job in jobs if job.get("name") in required
    )
):
    sys.exit("The successful CI attempt is missing a passed required job.")
' "$checked_run" "$checked_sha" "$attempt" || return
  printf '%s\n' "$attempt"
}

ci_attempt=$(verify_ci "$run_id" "$sha")
main_ci_run_id=$run_id
main_ci_attempt=$ci_attempt
verify_deploy_run() {
  github "actions/runs/$deploy_run_id/attempts/$deploy_attempt" | python3 -c '
import json, sys

run = json.load(sys.stdin)
common = (
    run.get("id") == int(sys.argv[1])
    and run.get("run_attempt") == int(sys.argv[2])
    and run.get("path") == ".github/workflows/deploy.yml"
    # GitHub can dispatch a self-hosted job before the run-status API catches
    # up from queued. This privileged script is invoked by that runner, so
    # accept either live state while retaining the exact run identity checks.
    and run.get("status") in {"queued", "in_progress"}
    and run.get("head_branch") == "main"
    and (run.get("head_repository") or {}).get("full_name") == sys.argv[3]
)
main_sha=run.get("head_sha")
if not common or not isinstance(main_sha,str) or len(main_sha)!=40:
    sys.exit("The production deployment run does not match this invocation.")
if sys.argv[5] == "incident":
    valid=run.get("event")=="workflow_dispatch"
elif sys.argv[5] == "manual":
    valid=(run.get("event")=="workflow_dispatch" and main_sha==sys.argv[4])
else:
    valid=(run.get("event")=="workflow_run"
           or (run.get("event")=="workflow_dispatch" and main_sha==sys.argv[4]))
if not valid:
    sys.exit("The production deployment run does not match this invocation.")
print(main_sha if sys.argv[5] == "incident" else sys.argv[4])
' "$deploy_run_id" "$deploy_attempt" "$repository" "$expected_main" \
    "$(if (( ${incident_replacement:-0} )); then echo incident; elif (( pinned || forward097 )); then echo manual; else echo automatic; fi)"
}
if (( pinned )); then
  consume_pinned_exception
fi
deployment_main_sha=$(verify_deploy_run)
if (( incident_replacement )); then
  expected_main=$deployment_main_sha
  github "compare/65308a2af263cd59e90276b3a771d4ed6ecbf842...$expected_main" | python3 -c '
import json,sys
comparison=json.load(sys.stdin)
if (comparison.get("status") not in {"ahead","identical"}
    or comparison.get("base_commit",{}).get("sha")!="65308a2af263cd59e90276b3a771d4ed6ecbf842"
    or comparison.get("merge_base_commit",{}).get("sha")!="65308a2af263cd59e90276b3a771d4ed6ecbf842"):
 sys.exit("The fixed green recovery candidate is no longer an ancestor of deployment main.")
'
  main_ci_run_id=$(github "actions/runs?head_sha=$expected_main&branch=main&event=push&per_page=100" | python3 -c '
import json,sys
response=json.load(sys.stdin)
runs=response.get("workflow_runs",[])
valid=[run for run in runs if run.get("path")==".github/workflows/ci.yml"
       and run.get("event")=="push" and run.get("head_branch")=="main"
       and run.get("head_sha")==sys.argv[1]
       and (run.get("head_repository") or {}).get("full_name")=="nirzaf/garrison-investments"]
if not valid: sys.exit("Exact deployment main SHA has no CI run.")
valid.sort(key=lambda run: (run.get("created_at",""),run.get("run_attempt",0)),reverse=True)
print(valid[0]["id"])
' "$expected_main")
  main_ci_attempt=$(verify_ci "$main_ci_run_id" "$expected_main")
fi
[[ "$deployment_main_sha" == "$expected_main" ]] || die 'Deployment workflow main SHA does not match the verified main tip.'
verify_main
if (( incident_replacement )); then
  github "actions/runs/44726033272" | python3 -c '
import json,sys
run=json.load(sys.stdin)
if (run.get("head_sha")!="60be439923df92e127540ffc9f0b509879797c1b"
    or run.get("event")!="push" or run.get("conclusion")!="failure"):
 sys.exit("The recorded predecessor CI failure does not match the incident.")
'
  verify_no_predecessor_production_deployment
  verify_forward_reconcile_tool
  python3 "$forward_reconcile_tool" preflight --lock-fd 9
fi
if (( forward097 )); then
  # Fixed protected installation, never execute privileged helper code from candidate.
  python3 - <<'PYFORWARD'
import hashlib,pathlib,stat
base=pathlib.Path('/usr/local/lib/garrison-release')
for path in (base.parent.parent,base.parent,base):
 info=path.lstat()
 if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
  raise SystemExit('Forward runtime installation is not protected')
expected={'forward097-runtime.sh': '52171806726020a99f8ccb93bfdb3e9bc040bcc26cdd13e0ffac246b2e3997ce', 'forward_release_contract.py': '318e661a5ced681fbe26c9a5dbc59c314bf26dfc1edb8c929306460440ee516d', 'consume-forward097.py': '0596e6125d70affe3ccf76b2f5e14213c158ced632cecb87ce9f3e1f9e802e93', 'forward097-schema.sql': 'b7bc5ea00f38bdd9e2a4dbd62646b5ec48a3d8b49c2ed9a2892eaf4f00342978', 'forward097-schema.json': '3aac1590deb8b6aafc68149b8acae60a675d1a0a4ca06827c03d6de006d36732'}
for name,digest in expected.items():
 path=base/name;info=path.lstat()
 if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
  raise SystemExit('Forward helper is not root-controlled')
 if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
  raise SystemExit('Forward helper bytes differ from reviewed entrypoint')
PYFORWARD
  source /usr/local/lib/garrison-release/forward097-runtime.sh
fi

check_readiness() {
  python3 -c '
import json, sys

if json.load(sys.stdin) != {"status": "ready", "database": "connected"}:
    sys.exit("The served readiness response does not report a connected database.")
'
}

previous=$(readlink -f "$state/current")
[[ "$previous" == "$base/releases/"* && -f "$previous/.env" ]] ||
  die 'The active production release has not been initialized.'
if (( pinned )); then
  [[ "$(cat "$previous/SOURCE_COMMIT")" == 21750a2a425f91b4d5811e8ac77f0e3ddec9deb8 ]] ||
    die 'Pinned exception requires the reviewed previous production release.'
fi
if [[ "$(cat "$previous/SOURCE_COMMIT")" == "$sha" ]]; then
  curl --fail --silent --show-error --max-time 10 "$portal/health/readiness" | check_readiness
  printf '\nCommit %s is already deployed.\n' "$sha"
  exit 0
fi

phase_started=$SECONDS
candidate=$(mktemp -d "$base/releases/$sha.XXXXXX")
github "tarball/$sha" | (umask 022; tar -xzf - --strip-components=1 --no-same-owner --no-same-permissions -C "$candidate")
for reserved in .env .images.env .incident-nginx-override.yml SOURCE_COMMIT DEPLOYED ACTIVATION_FAILED READINESS.json FORWARD_NGINX.conf FORWARD_COMPOSE.json; do
  [[ ! -e "$candidate/$reserved" && ! -L "$candidate/$reserved" ]] ||
    die 'The source archive contains a reserved release file.'
done
install -m 0600 "$state/production.env" "$candidate/.env"
printf '%s\n' "$sha" > "$candidate/SOURCE_COMMIT"
incident_nginx_override="$candidate/.incident-nginx-override.yml"
if (( incident_replacement )); then
  printf 'services:\n  nginx:\n    image: %s\n' "$patched_nginx_image" > "$incident_nginx_override"
  chmod 0600 "$incident_nginx_override"
fi
report_duration 'CI verification and source preparation' "$phase_started"

generation=$(cat "$candidate/deploy/rollback-generation")
[[ "$generation" =~ ^[1-9][0-9]*$ ]] || die 'Invalid candidate rollback generation.'
previous_generation=
if [[ -f "$previous/deploy/rollback-generation" ]]; then
  previous_generation=$(cat "$previous/deploy/rollback-generation")
fi

if [[ "$generation" != "$previous_generation" ]]; then
  running=$(docker ps --filter "label=com.docker.compose.project=$project" \
    --filter 'label=com.docker.compose.oneoff=False' \
    --format '{{.Label "com.docker.compose.service"}}')
  if [[ "$running" =~ (^|[[:space:]])(nginx|backend|celery_worker|celery_beat)([[:space:]]|$) ]]; then
    die 'Rollback generation changed. Stop production ingress and application writers during maintenance before retrying.'
  fi
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
   ! cmp -s "$previous/.env" "$candidate/.env" ||
   ! same_backend_runtime "$previous/backend" "$candidate/backend" ||
   ! cmp -s "$previous/docker-compose.prod.yml" "$candidate/docker-compose.prod.yml" ||
   ! diff -qr --exclude=ssl "$previous/nginx" "$candidate/nginx" >/dev/null ||
   ! diff -qr "$previous/observability" "$candidate/observability" >/dev/null; then
  runtime_changed=1
fi
if (( ${incident_replacement:-0} )); then
  # Never attest/release a candidate while retaining the image from the
  # unattested predecessor, even when the application tree is unchanged.
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
  local proxy_override="$directory/.incident-nginx-override.yml"
  local -a compose_files=(-f "$directory/docker-compose.prod.yml" -f "$state/compose.vps.yml")
  if (( incident_replacement )); then
    proxy_override=$incident_nginx_override
  fi
  if [[ -e "$proxy_override" || -L "$proxy_override" ]]; then
    [[ -f "$proxy_override" && ! -L "$proxy_override" && -O "$proxy_override" &&
       "$(stat -c '%a' "$proxy_override")" == 600 ]] || die 'Incident Nginx override is unsafe.'
    printf 'services:\n  nginx:\n    image: %s\n' "$patched_nginx_image" |
      cmp -s - "$proxy_override" || die 'Incident Nginx override differs from the reviewed digest.'
    compose_files+=(-f "$proxy_override")
  fi
  docker compose --project-name "$project" --project-directory "$directory" \
    --env-file "$directory/.env" --env-file "$directory/.images.env" \
    "${compose_files[@]}" "$@"
}

phase_started=$SECONDS
# Validate host configuration files, runtime secrets/TLS/key mounts, and log-retention safety directly.
candidate_compose_file=$(mktemp)
network_inspect_file=
cleanup_preflight_files() {
  [[ -z "${candidate_compose_file:-}" ]] || rm -f -- "$candidate_compose_file"
  [[ -z "${network_inspect_file:-}" ]] || rm -f -- "$network_inspect_file"
}
trap cleanup_preflight_files EXIT
if ! compose "$candidate" config --format json > "$candidate_compose_file" ||
   ! python3 - "$base" "$state" "$candidate" "$candidate_compose_file" "$((pinned || forward097))" "$release_mode" <<'PY'; then
import json
import os
import stat
import sys
from pathlib import Path

base, state, candidate, compose_path = (Path(arg) for arg in sys.argv[1:5])
false_tokens = {"false", "0", "no", "off"}

def within_root(path: Path, root: Path) -> Path | None:
    raw_path = Path(os.path.normpath(str(path)))
    raw_root = Path(os.path.normpath(str(root)))
    try:
        rel = raw_path.relative_to(raw_root)
        return raw_root / rel
    except ValueError:
        pass
    try:
        rel = path.resolve().relative_to(root.resolve())
        return Path(os.path.normpath(str(root))) / rel
    except ValueError:
        return None

def check_no_symlinks_under(path: Path, root: Path) -> None:
    norm_root = Path(os.path.normpath(str(root)))
    rel = path.relative_to(norm_root)
    current = norm_root
    if current.is_symlink():
        raise SystemExit(f"{current} must not be a symlink")
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise SystemExit(f"{path} traverses symlink {current}")
        if not current.exists():
            raise SystemExit(f"{path} is missing path component {current}")

def require_regular_file(path: Path, *, root: Path, mask: int = 0o022) -> bytes:
    mapped = within_root(path, root)
    if mapped is None:
        raise SystemExit(f"{path} resolves outside {root}")
    check_no_symlinks_under(mapped, root)
    st = mapped.lstat()
    if not stat.S_ISREG(st.st_mode):
        raise SystemExit(f"{mapped} must be a regular file")
    if st.st_size <= 0:
        raise SystemExit(f"{mapped} must not be empty")
    if st.st_mode & mask:
        raise SystemExit(f"{mapped} has unsafe permissions {oct(st.st_mode & 0o777)}")
    return mapped.read_bytes()

def parse_env(raw: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in raw.decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            raise SystemExit("Invalid line in production environment file")
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if val and val[0] in {"'", '"'} and len(val) >= 2 and val[-1] == val[0]:
            val = val[1:-1]
        else:
            val = val.split(" #", 1)[0].strip()
        values[key] = val
    return values

prod_env_bytes = require_regular_file(state / "production.env", root=state, mask=0o077)
require_regular_file(state / "compose.vps.yml", root=state, mask=0o022)
cand_env_bytes = require_regular_file(candidate / ".env", root=candidate, mask=0o077)
if cand_env_bytes != prod_env_bytes:
    raise SystemExit("Candidate .env does not match host production.env")

for rel in (
    "deploy/rollback-generation",
    "docker-compose.prod.yml",
    "observability/postgres/init-grafana-db.sh",
    "observability/minio/loki-policy.json",
):
    require_regular_file(candidate / rel, root=candidate, mask=0o022)

for subdir in ("nginx", "observability"):
    root_dir = candidate / subdir
    if root_dir.exists() or root_dir.is_symlink():
        check_no_symlinks_under(within_root(root_dir, candidate) or root_dir, candidate)
        for item in sorted(root_dir.rglob("*")):
            mapped_item = within_root(item, candidate)
            if mapped_item is None:
                raise SystemExit(f"{item} resolves outside candidate directory")
            check_no_symlinks_under(mapped_item, candidate)
            st = mapped_item.lstat()
            if st.st_mode & 0o022:
                raise SystemExit(f"{mapped_item} is group or world writable")
            if stat.S_ISREG(st.st_mode) and mapped_item.name != ".gitkeep" and st.st_size <= 0:
                raise SystemExit(f"{mapped_item} must not be empty")

env_values = parse_env(cand_env_bytes)
if sys.argv[5] == "1" and env_values.get("SUPPORT_PORTAL_ENABLED", "false").lower() != "false":
    raise SystemExit("Super Admin ingress must remain disabled during the pinned rollout.")
if env_values.get("LOG_PURGE_ENABLED", "").strip().lower() not in false_tokens:
    raise SystemExit("Production audit deletion must be disabled (LOG_PURGE_ENABLED=false).")
release_mode = sys.argv[6]

cfg = json.loads(compose_path.read_text(encoding="utf-8"))
services = cfg.get("services")
if not isinstance(services, dict) or not services:
    raise SystemExit("Effective Compose configuration is missing services")
nginx_service = services.get("nginx")
if not isinstance(nginx_service, dict) or nginx_service.get("image") != (
    "nginx:1.30.7-alpine@sha256:caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3"
):
    raise SystemExit("Effective Nginx service configuration is invalid")

sys.path.insert(0, str(candidate / "deploy"))
from release_config_contract import validate_pinned_service_environment, validate_support_ingress

for svc_name in ("backend", "celery_worker", "celery_beat"):
    svc = services.get(svc_name)
    if not isinstance(svc, dict):
        raise SystemExit(f"Effective Compose configuration is missing service {svc_name}")
    try:
        env = validate_pinned_service_environment(svc_name, svc, env_values)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if "LOG_PURGE_ENABLED" in env:
        purge_val = env.get("LOG_PURGE_ENABLED")
        if not isinstance(purge_val, (str, int, bool)) or str(purge_val).strip().lower() not in false_tokens:
            raise SystemExit("Production audit deletion must be disabled (LOG_PURGE_ENABLED=false).")
if release_mode == "incident-replacement":
    # The fixed 65308a2 recovery archive predates the file-based secret
    # contract. Accept its legacy variable only for this exact incident mode;
    # ordinary releases must use the protected read-only secret-file mount.
    if (
        "BACKUP_ENCRYPTION_PASSWORD" not in env_values
        or "BACKUP_ENCRYPTION_KEY_HOST_FILE" in env_values
    ):
        raise SystemExit("The incident replacement requires its verified legacy backup-secret contract.")
else:
    try:
        from release_config_contract import validate_backup_secret_configuration
    except ImportError as error:
        raise SystemExit("Candidate is missing file-based backup-secret validation.") from error
    try:
        validate_backup_secret_configuration(env_values, services)
    except ValueError as error:
        raise SystemExit(str(error)) from error

mounted_files_by_target: dict[str, Path] = {}
nginx_files_by_target: dict[str, Path] = {}
mounted_dirs_by_target: dict[str, Path] = {}
mounted_sources: list[Path] = []

for svc_name, svc in services.items():
    if not isinstance(svc, dict):
        raise SystemExit(f"Service {svc_name} definition is invalid")
    volumes = svc.get("volumes") or []
    if not isinstance(volumes, list):
        raise SystemExit(f"Service {svc_name} volumes must be a list")
    for vol in volumes:
        if not isinstance(vol, dict) or vol.get("type") != "bind":
            continue
        source_raw = str(vol.get("source") or "").strip()
        target_raw = str(vol.get("target") or "").strip().rstrip("/") or "/"
        if not source_raw:
            raise SystemExit(f"Service {svc_name} has a bind mount without source")
        if source_raw == "/var/run/docker.sock":
            continue
        source_path = Path(source_raw)
        if not source_path.is_absolute():
            source_path = candidate / source_path
        stop_root = candidate if within_root(source_path, candidate) is not None else base
        mapped = within_root(source_path, stop_root)
        if mapped is None:
            raise SystemExit(f"Service {svc_name} bind mount {source_raw} escapes {base}")
        check_no_symlinks_under(mapped, stop_root)
        st = mapped.lstat()
        if st.st_mode & 0o022:
            raise SystemExit(f"Bind mount source {mapped} is group or world writable")
        if stat.S_ISREG(st.st_mode):
            if st.st_size <= 0:
                raise SystemExit(f"Bind mount file {mapped} must not be empty")
            mounted_files_by_target[target_raw] = mapped
            if svc_name == "nginx":
                nginx_files_by_target[target_raw] = mapped
            mounted_sources.append(mapped)
        elif stat.S_ISDIR(st.st_mode):
            has_file = False
            for member in sorted(mapped.rglob("*")):
                mapped_member = within_root(member, stop_root)
                if mapped_member is None:
                    raise SystemExit(f"Bind mount member {member} escapes {stop_root}")
                check_no_symlinks_under(mapped_member, stop_root)
                mst = mapped_member.lstat()
                if mst.st_mode & 0o022:
                    raise SystemExit(f"Bind mount member {mapped_member} is group or world writable")
                if stat.S_ISREG(mst.st_mode):
                    has_file = True
                    if mapped_member.name == ".gitkeep":
                        continue
                    if mst.st_size <= 0:
                        raise SystemExit(f"Bind mount file {mapped_member} must not be empty")
                    rel_member = mapped_member.relative_to(mapped).as_posix()
                    mounted_files_by_target[f"{target_raw}/{rel_member}"] = mapped_member
                    if svc_name == "nginx":
                        nginx_files_by_target[f"{target_raw}/{rel_member}"] = mapped_member
                    mounted_sources.append(mapped_member)
            if not has_file:
                raise SystemExit(f"Bind mount directory {mapped} must contain at least one non-empty file")
            mounted_dirs_by_target[target_raw] = mapped
        else:
            raise SystemExit(f"Bind mount source {mapped} must be a regular file or directory")

try:
    validate_support_ingress(
        candidate, services.get("nginx") or {}, services["backend"], env_values, nginx_files_by_target
    )
except ValueError as error:
    raise SystemExit(str(error)) from error

# Verify TLS certificate files are mounted via /etc/nginx/ssl or matching paths.
tls_fullchain = mounted_files_by_target.get("/etc/nginx/ssl/fullchain.pem") or next(
    (p for p in mounted_sources if p.as_posix().endswith("/nginx/ssl/fullchain.pem")), None
)
tls_privkey = mounted_files_by_target.get("/etc/nginx/ssl/privkey.pem") or next(
    (p for p in mounted_sources if p.as_posix().endswith("/nginx/ssl/privkey.pem")), None
)
if tls_fullchain is None or tls_privkey is None or tls_fullchain.parent != tls_privkey.parent:
    raise SystemExit("Effective Compose configuration omits a valid TLS fullchain/privkey mount")

# Verify JWT signing keys are mounted for production token signing and verification.
jwt_priv_target = env_values.get("JWT_PRIVATE_KEY_PATH", "/run/secrets/jwt_private_key").rstrip("/")
jwt_pub_target = env_values.get("JWT_PUBLIC_KEY_PATH", "/run/secrets/jwt_public_key").rstrip("/")
jwt_priv = (
    mounted_files_by_target.get(jwt_priv_target)
    or mounted_files_by_target.get("/run/secrets/jwt_private_key")
    or next((p for p in mounted_sources if p.as_posix().endswith("/secrets/jwt_private_key")), None)
)
jwt_pub = (
    mounted_files_by_target.get(jwt_pub_target)
    or mounted_files_by_target.get("/run/secrets/jwt_public_key")
    or next((p for p in mounted_sources if p.as_posix().endswith("/secrets/jwt_public_key")), None)
)
if jwt_priv is None or jwt_pub is None:
    raise SystemExit("Effective Compose configuration omits a valid JWT signing key mount")
PY
  rm -f "$candidate_compose_file"
  die 'Effective runtime configuration failed technical configuration, secret/TLS/key, or log-retention safety validation.'
fi
# Build from the tested archive. Docker can reuse its layer cache.
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

# `docker compose run` inherits the Nginx service's fixed backend_proxy IP.
# The production Nginx container already owns that address, so validation must
# select a temporary, unused address on the same private network. Keep the
# original Compose configuration and all active containers unchanged.
nginx_test_network=$(python3 - "$candidate_compose_file" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
nginx = config.get("services", {}).get("nginx", {})
attachments = nginx.get("networks", {})
fixed = [
    name for name, settings in attachments.items()
    if isinstance(settings, dict) and settings.get("ipv4_address")
]
if len(fixed) != 1:
    raise SystemExit("Nginx test requires exactly one fixed private IPv4 network.")
alias = fixed[0]
network = config.get("networks", {}).get(alias, {})
name = network.get("name", alias)
if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
    raise SystemExit("Nginx test network name is invalid.")
print(name)
PY
) || die 'Unable to determine the Nginx private test network.'
network_inspect_file=$(mktemp)
docker network inspect "$nginx_test_network" > "$network_inspect_file" ||
  die 'Unable to inspect the Nginx private test network.'
nginx_test_ip=$(python3 - "$candidate_compose_file" "$network_inspect_file" <<'PY'
import ipaddress
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    compose_config = json.load(stream)
with open(sys.argv[2], encoding="utf-8") as stream:
    inspected = json.load(stream)
nginx = compose_config["services"]["nginx"]
attachments = nginx.get("networks", {})
fixed = [
    (name, settings)
    for name, settings in attachments.items()
    if isinstance(settings, dict) and settings.get("ipv4_address")
]
if len(fixed) != 1:
    raise SystemExit("Nginx test requires exactly one fixed private IPv4 network.")
alias, attachment = fixed[0]
network_config = compose_config["networks"].get(alias, {})
network_name = network_config.get("name", alias)
matches = [item for item in inspected if item.get("Name") == network_name]
if len(matches) != 1:
    raise SystemExit("Nginx private network inspection is ambiguous.")
network = matches[0]
expected_configs = network_config.get("ipam", {}).get("config", [])
actual_configs = network.get("IPAM", {}).get("Config", [])
if len(expected_configs) != 1 or len(actual_configs) != 1:
    raise SystemExit("Nginx private network must have one explicit IPv4 subnet.")
expected = expected_configs[0]
actual = actual_configs[0]
subnet = ipaddress.ip_network(expected["subnet"], strict=True)
if subnet.version != 4 or str(subnet) != actual.get("Subnet"):
    raise SystemExit("Rendered and live Nginx network subnets differ.")
expected_range = expected.get("ip_range", "")
actual_range = actual.get("IPRange", "")
if expected_range != actual_range:
    raise SystemExit("Rendered and live Nginx dynamic IP ranges differ.")
expected_gateway = expected.get("gateway", "")
actual_gateway = actual.get("Gateway", "")
if expected_gateway and expected_gateway != actual_gateway:
    raise SystemExit("Rendered and live Nginx gateways differ.")
if actual_gateway and ipaddress.ip_address(actual_gateway) not in subnet:
    raise SystemExit("Live Nginx gateway is outside its private subnet.")
requested = ipaddress.ip_address(attachment["ipv4_address"])
if requested not in subnet:
    raise SystemExit("Configured Nginx address is outside its private subnet.")
first_host = next(subnet.hosts(), None)
excluded = {requested}
if first_host is not None:
    excluded.add(first_host)
if actual_gateway:
    excluded.add(ipaddress.ip_address(actual_gateway))
for endpoint in network.get("Containers", {}).values():
    address = endpoint.get("IPv4Address", "").split("/", 1)[0]
    if address:
        parsed = ipaddress.ip_address(address)
        if parsed.version == 4:
            excluded.add(parsed)
dynamic_range = ipaddress.ip_network(actual_range, strict=True) if actual_range else None
for candidate in subnet.hosts():
    if candidate in excluded:
        continue
    if dynamic_range is not None and candidate in dynamic_range:
        continue
    print(candidate)
    break
else:
    raise SystemExit("No collision-free static IPv4 address is available for Nginx validation.")
PY
) || die 'No verified collision-free IPv4 address is available for Nginx validation.'
NGINX_BACKEND_PROXY_IP="$nginx_test_ip" compose "$candidate" run --rm --no-deps -T nginx nginx -t
cleanup_preflight_files
candidate_compose_file=
network_inspect_file=
trap - EXIT
report_duration 'Image preparation and configuration checks' "$phase_started"

backend_id=$(docker image inspect --format '{{.Id}}' "$backend_image")
frontend_id=$(docker image inspect --format '{{.Id}}' "$frontend_image")
heads=$(image_heads "$backend_image")
current=$(docker exec "$project-postgres-1" sh -ec \
  'psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version"' | sort)
if (( forward097 )); then
  [[ "$current" == 202605310093 && "$heads" == 202605310097 && "$runtime_changed" == 1 ]] ||
    die 'Forward exception requires exact093 to097 and candidate runtime.'
elif (( pinned )); then
  [[ "$current" == 202605310061 && "$heads" == 202605310093 && "$runtime_changed" == 1 ]] ||
    die 'Pinned exception requires the exact 061 to 093 migration and runtime switch.'
elif (( incident_replacement )); then
  [[ "$current" == 202605310097 && "$heads" == "$current" && "$runtime_changed" == 1 &&
     "$backend_image" == "garrison-portal-release-backend:$sha" ]] ||
    die 'Incident replacement requires an exact 097 schema match and a freshly built candidate image.'
else
  [[ -n "$heads" && "$heads" == "$current" ]] ||
    die 'Pending database migrations require the reviewed maintenance procedure.'
fi

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
  local actual_nginx_image nginx_version
  actual_nginx_image=$(docker inspect --format '{{.Config.Image}}' "$project-nginx-1") || return
  [[ "$actual_nginx_image" == "$patched_nginx_image" ]] || return 1
  nginx_version=$(docker exec "$project-nginx-1" nginx -v 2>&1) || return
  [[ "$nginx_version" == 'nginx version: nginx/1.30.7' ]] || return 1
  docker exec "$project-nginx-1" nginx -s reload
}

rollback_compatible=0
if (( ! pinned && ! forward097 )) && [[ "$generation" == "$previous_generation" ]]; then
  old_backend=$(sed -n 's/^GARRISON_BACKEND_IMAGE=//p' "$previous/.images.env")
  old_frontend=$(sed -n 's/^GARRISON_FRONTEND_IMAGE=//p' "$previous/.images.env")
  if [[ -n "$old_backend" && -n "$old_frontend" ]] &&
     old_heads=$(image_heads "$old_backend") && [[ "$old_heads" == "$current" ]] &&
     docker image inspect "$old_frontend" >/dev/null; then
    rollback_compatible=1
  fi
fi
if (( ${incident_replacement:-0} && !rollback_compatible )); then
  die 'Incident replacement requires a verified same-schema rollback image before activation.'
fi
runtime_attempted=0
frontend_attempted=0
pointer_advanced=0
previous_nginx_id=
previous_nginx_image=
if (( ${incident_replacement:-0} )); then
  previous_nginx_id=$(docker inspect --format '{{.Id}}' "$project-nginx-1")
  previous_nginx_image=$(docker inspect --format '{{.Config.Image}}' "$project-nginx-1")
fi

rollback() {
  local result=$?
  if (( result && (runtime_attempted || frontend_attempted) )); then
    set +e
    if (( forward097 )); then
      forward_contain || printf 'Forward containment incomplete; operator intervention required.\n' >&2
    elif (( rollback_compatible )); then
      printf 'Activation failed. Restoring the previous compatible application release.\n' >&2
      if (( runtime_attempted )); then
        apply_runtime "$previous" || printf 'Application rollback failed. Check the production services.\n' >&2
      fi
      if (( frontend_attempted )); then
        publish_frontend "$old_frontend" || printf 'Frontend rollback failed. Restore the compatible static bundle.\n' >&2
      fi
    else
      printf 'Activation failed without a compatible rollback. Keep the maintenance write block in place and recover forward.\n' >&2
      printf 'Commit: %s\nCI run: %s\nCI attempt: %s\nUTC: %s\nExit: %s\n' \
        "$sha" "$run_id" "$ci_attempt" "$(date -u +%FT%TZ)" "$result" \
        > "$candidate/ACTIVATION_FAILED"
      compose "$candidate" stop nginx celery_beat celery_worker backend ||
        printf 'Automatic containment failed. Stop portal ingress and writers from the host.\n' >&2
    fi
    if (( pointer_advanced && rollback_compatible )); then
      ln -sfn "$previous" "$state/.current-rollback" &&
        mv -Tf "$state/.current-rollback" "$state/current" ||
        printf 'Release pointer rollback failed. Keep CD disabled and reconcile the host state.\n' >&2
    fi
  fi
  exit "$result"
}

trap rollback EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
phase_started=$SECONDS
if (( forward097 )); then
  forward_release
elif (( pinned )); then
  assert_pinned_window
  verify_main
  running=$(docker ps --filter "label=com.docker.compose.project=$project" \
    --format '{{.Label "com.docker.compose.service"}}')
  if [[ "$running" =~ (^|[[:space:]])(nginx|backend|celery_worker|celery_beat)([[:space:]]|$) ]]; then
    die 'Pinned migration requires stopped ingress and application writers.'
  fi
  remaining_clients=$(docker exec "$project-postgres-1" sh -ec \
    'psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() AND backend_type = '\''client backend'\''"')
  [[ "$remaining_clients" == 0 ]] ||
    die 'Pinned migration requires all application database client sessions to be drained.'
  assert_pinned_window
  printf '%s\n' 'Owner-approved pinned release without a secured backup. Independent recovery pending.' \
    > "$candidate/RECOVERY_EXCEPTION"
  runtime_attempted=1
  compose "$candidate" run --rm --no-deps --pull never -T backend alembic upgrade 202605310093
  current=$(docker exec "$project-postgres-1" sh -ec \
    'psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version"' | sort)
  [[ "$current" == "$heads" ]] || die 'Pinned production migration did not reach the authorized head.'
else
  compose "$candidate" run --rm --no-deps --pull never -T backend \
    python -m scripts.backup --target all --skip-retention
  report_duration 'Pre-activation backup' "$phase_started"
fi
verify_main
unset token
phase_started=$SECONDS
if (( pinned )); then
  assert_pinned_window
fi
if (( runtime_changed && ! forward097 )); then
  runtime_attempted=1
  apply_runtime "$candidate"
  if (( incident_replacement )) && [[ "$previous_nginx_image" != "$patched_nginx_image" ]] &&
     docker inspect "$previous_nginx_id" >/dev/null 2>&1; then
    die 'The previous Nginx container is still present after patched proxy activation.'
  fi
fi
if (( ! forward097 )); then
  frontend_attempted=1
  publish_frontend "$frontend_image"
fi
report_duration 'Activation' "$phase_started"

phase_started=$SECONDS
verification_services="backend celery_worker celery_beat"
if (( forward097 )); then verification_services=backend; fi
for service in $verification_services; do
  container=$(compose "$candidate" ps -q "$service")
  [[ -n "$container" && "$(docker inspect --format '{{.Image}}' "$container")" == "$backend_id" ]] ||
    die "The active $service image differs from the candidate backend build."
done
actual=$(curl --fail --silent --show-error --retry 4 --max-time 12 "$portal/login" | hash)
[[ "$expected" == "$actual" ]] || die 'The served sign-in page differs from the release image.'
actual_asset=$(curl --fail --silent --show-error --retry 4 --max-time 12 "$portal$asset" | hash)
[[ "$expected_asset" == "$actual_asset" ]] || die 'The served JavaScript differs from the release image.'
actual_worker=$(curl --fail --silent --show-error --retry 4 --max-time 12 "$portal/sw.js" | hash)
[[ "$expected_worker" == "$actual_worker" ]] || die 'The served service worker differs from the release image.'
curl --fail --silent --show-error --retry 4 --max-time 12 "$portal/health/readiness" > "$candidate/READINESS.json"
check_readiness < "$candidate/READINESS.json"
report_duration 'Live image and readiness verification' "$phase_started"
cat "$candidate/READINESS.json"

printf 'Status: Deployed — Formal Acceptance Pending\nCommit: %s\nCI run: %s\nCI attempt: %s\nDeploy run: %s\nDeploy attempt: %s\nUTC: %s\nFrontend asset: %s\nAsset SHA-256: %s\nService worker SHA-256: %s\nBackend image: %s\nFrontend image: %s\nSchema heads: %s\n' \
  "$sha" "$run_id" "$ci_attempt" "$deploy_run_id" "$deploy_attempt" "$(date -u +%FT%TZ)" \
  "$asset" "$expected_asset" "$expected_worker" \
  "$backend_id" "$frontend_id" "$(tr '\n' ' ' <<< "$current")" > "$candidate/DEPLOYED"
if (( forward097 )); then mv "$candidate/DEPLOYED" "$candidate/FORWARD_ACTIVATION_PENDING"; fi
ln -sfn "$candidate" "$state/.current-next"
mv -Tf "$state/.current-next" "$state/current"
pointer_advanced=1
if (( forward097 )); then
  printf 'Mode: forward-only-093-to-097\nSecured backup/restore: waived for exact owner-authorized release; not verified\n' >> "$candidate/FORWARD_ACTIVATION_PENDING"
  python3 - "$candidate" "$state" <<'PYFS'
import os,sys
from pathlib import Path
candidate,state=map(Path,sys.argv[1:])
with (candidate/'FORWARD_VERIFIED').open('x') as f:
    f.write('Guarded image/schema/readiness verified; current pointer committed.\n')
    f.flush();os.fsync(f.fileno())
for path in (candidate/'FORWARD_ACTIVATION_PENDING',candidate,state):
    fd=os.open(path,os.O_RDONLY);os.fsync(fd);os.close(fd)
PYFS
  forward_mark deployed_pointer_verified
  forward_reopen
  for service in celery_worker celery_beat; do
    container=$(compose "$candidate" ps -q "$service")
    [[ "$(docker inspect --format '{{.Image}}' "$container")" == "$backend_id" ]] || die 'Reopened writer image mismatch.'
  done
  curl --fail --silent --show-error --max-time 12 "$portal/health/readiness" | check_readiness
  forward_mark reopened_verified
  mv "$candidate/FORWARD_ACTIVATION_PENDING" "$candidate/DEPLOYED"
fi
if (( incident_replacement )); then
  verify_forward_reconcile_tool
  python3 "$forward_reconcile_tool" close --lock-fd 9 \
    --sha "$sha" --ci-run "$run_id" --ci-attempt "$ci_attempt" \
    --main-sha "$expected_main" --main-ci-run "$main_ci_run_id" --main-ci-attempt "$main_ci_attempt" \
    --deploy-run "$deploy_run_id" --deploy-attempt "$deploy_attempt"
fi
trap - EXIT INT TERM
printf '\nDeployed %s from CI run %s. Frontend asset %s verified.\n' "$sha" "$run_id" "$asset"
