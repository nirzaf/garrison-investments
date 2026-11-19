forward_verify_schema() {
  docker exec -i "$project-postgres-1" sh -ec 'psql -XqAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < /usr/local/lib/garrison-release/forward097-schema.sql | python3 -c '
import json,sys
from pathlib import Path
actual=json.load(sys.stdin)
expected=json.loads(Path("/usr/local/lib/garrison-release/forward097-schema.json").read_text())
if actual!=expected:sys.exit("Exact097 schema integrity mismatch; keep maintenance closed")
'
}
forward_permit() {
  python3 /usr/local/lib/garrison-release/consume-forward097.py "$1" "$state" "$sha" "$run_id" "$ci_attempt" "$deploy_run_id" "$deploy_attempt" "$(sha256sum /usr/local/sbin/garrison-deploy | cut -d' ' -f1)"
}
# Root-installed, byte-bound extension of garrison-deploy. Never source from candidate.
# Uses the entrypoint's verified SHA/CI, Compose wrapper and validated protected config.
forward_compose() { local root=$1; shift; compose "$root" -f "$root/FORWARD_COMPOSE.json" "$@"; }
forward_schema() {
  docker exec "$project-postgres-1" sh -ec 'psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version"'
}
forward_clients() {
  docker exec "$project-postgres-1" sh -ec 'psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='\''client backend'\''"'
}
forward_mark() {
  python3 - "$state/forward097.attempt" "$1" <<'PY'
import json,os,sys
fd=os.open(sys.argv[1],os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW)
try:
    os.write(fd,(json.dumps({'phase':sys.argv[2]})+'\n').encode());os.fsync(fd)
finally:os.close(fd)
PY
}
forward_warm_stop() {
  local service=$1 id running signalled=0 start=$SECONDS
  id=$(docker ps -aq --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=$service" --filter label=com.docker.compose.oneoff=False)
  [[ -n "$id" && "$id" != *$'\n'* ]] || return 1
  while true; do
    running=$(docker inspect --format '{{.State.Running}} {{.State.Status}}' "$id") || return 1
    case "$running" in
      'false exited'|'false created')
        [[ "$(docker ps -aq --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=$service" --filter label=com.docker.compose.oneoff=False)" == "$id" ]] || return 1
        [[ "$(docker inspect --format '{{.State.Running}} {{.State.Status}}' "$id")" == "$running" ]] || return 1
        return 0 ;;
      'true running') ;;
      *) return 1 ;;
    esac
    if (( ! signalled )); then docker kill --signal TERM "$id" >/dev/null || return 1; signalled=1; fi
    (( SECONDS-start < 120 )) || return 1
    sleep 1
  done
}
forward_contain() {
  local service failed=0
  for service in nginx celery_beat celery_worker backend; do
    forward_warm_stop "$service" || failed=1
  done
  if (( failed )); then forward_mark containment_unknown; else forward_mark contained_failure; fi
  return "$failed"
}
forward_inventory() {
  local ids
  ids=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
  [[ -n "$ids" ]] || die 'Forward maintenance cannot discover the existing project.'
  docker inspect $ids | python3 -c '
import json,sys
objects=json.load(sys.stdin); project=sys.argv[1]
allowed={"nginx","backend","celery_worker","celery_beat","postgres","redis","minio","grafana","loki","alloy","frontend_dist","grafana_db_init","loki_minio_init"}
writers={"nginx","backend","celery_worker","celery_beat"}; seen=set()
for obj in objects:
    labels=obj["Config"].get("Labels") or {}; service=labels.get("com.docker.compose.service")
    if service not in allowed:sys.exit("Unknown project service blocks maintenance")
    if obj["State"]["Running"] and labels.get("com.docker.compose.oneoff")=="True":sys.exit("Running one-off blocks maintenance")
    if service in writers and labels.get("com.docker.compose.oneoff")!="True":
        if service in seen:sys.exit("Duplicate application service")
        seen.add(service)
        if obj["HostConfig"]["RestartPolicy"]["Name"] not in ("no",""):sys.exit("Unexpected writer restart policy")
        if service!="nginx" and obj["HostConfig"].get("PortBindings"):sys.exit("Direct application port blocks maintenance")
if seen!=writers:sys.exit("Incomplete application inventory")
' "$project"
}
forward_idle() {
  local operation id start=$SECONDS
  id=$(compose "$previous" ps -q celery_worker)
  [[ -n "$id" ]] || return 1
  for operation in active reserved scheduled; do
    while ! docker exec "$id" celery -A app.tasks.celery_app.celery_app inspect "$operation" --json --timeout=3 | python3 -c '
import json,sys
r=json.load(sys.stdin)
if not isinstance(r,dict) or len(r)!=1 or any(not isinstance(v,list) or v for v in r.values()):sys.exit(1)
'; do
      (( SECONDS-start < 120 )) || return 1
      sleep 1
    done
  done
}
forward_data_check() {
  docker exec -i "$project-postgres-1" sh -ec 'psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM support_bootstrap WHERE id<>1 OR second_id IS NULL OR first_id=second_id) THEN RAISE EXCEPTION 'Existing bootstrap rows need review'; END IF;
 IF EXISTS(SELECT 1 FROM support_case_actions WHERE (applied_at IS NULL)<>(reviewer_id IS NULL)) THEN RAISE EXCEPTION 'Existing action rows need review'; END IF;
 IF EXISTS(SELECT 1 FROM support_evidence_exports WHERE (approved_at IS NULL)<>(review_request_id IS NULL) OR (downloaded_at IS NULL)<>(download_request_id IS NULL) OR (downloaded_at IS NOT NULL AND approved_at IS NULL) OR (approved_at IS NULL)<>(reviewer_id IS NULL) OR (approved_at IS NULL)<>(reviewer_epoch IS NULL)) THEN RAISE EXCEPTION 'Existing export rows need review'; END IF;
END $$;
SQL
}
forward_prepare_guard() {
  compose "$previous" config --format json > "$candidate/FORWARD_PREVIOUS.json"
  compose "$candidate" config --format json | python3 -c '
import json,pathlib,re,sys
root=pathlib.Path(sys.argv[1]); c=json.load(sys.stdin)
old=json.loads((root/"FORWARD_PREVIOUS.json").read_text())
if set(c["services"])!=set(old["services"]) or c.get("networks")!=old.get("networks"):sys.exit("Service/network topology changed")
for name,svc in c["services"].items():
 prior=old["services"][name]
 for field in ("ports","network_mode","networks","extra_hosts"):
  if svc.get(field)!=prior.get(field):sys.exit("Candidate ingress/network topology changed")
 if name in {"backend","celery_worker","celery_beat","nginx"}:
  if svc.get("restart","no")!="no":sys.exit("Candidate writer restart policy must be no")
  if name!="nginx" and svc.get("ports"):sys.exit("Candidate direct backend port")
  if svc.get("network_mode") or svc.get("privileged"):sys.exit("Unsupported writer network/privilege")
m=[v for v in c["services"]["nginx"].get("volumes",[]) if v.get("target")=="/etc/nginx/conf.d/default.conf"]
if len(m)!=1 or m[0].get("type")!="bind" or not m[0].get("read_only"):sys.exit("Exact read-only nginx bind required")
src=pathlib.Path(m[0]["source"]); text=src.read_text()
guard="\n    # FORWARD097_MAINTENANCE_GUARD\n    if ($request_method !~ ^(GET|HEAD)$) { return 503; }\n    if ($uri !~ \"^(/|/login|/sw\\.js|/assets/[A-Za-z0-9_.-]+|/health/readiness)$\") { return 503; }\n"
if "FORWARD097_MAINTENANCE_GUARD" in text:sys.exit("Unexpected existing maintenance guard")
text,count=re.subn(r"(?m)^(\s*server\s*\{)\s*$",lambda m:m.group(1)+guard,text)
if count<1:sys.exit("Unsupported nginx syntax")
path=root/"FORWARD_NGINX.conf";path.write_text(text)
override={"services":{"nginx":{"volumes":[{"type":"bind","source":str(path),"target":"/etc/nginx/conf.d/default.conf","read_only":True}]}}}
(root/"FORWARD_COMPOSE.json").write_text(json.dumps(override))
' "$candidate"
  forward_compose "$candidate" config --quiet
}
forward_smoke() {
  local path code actual
  for path in /api/v1/projects /api/v1/auth/login /api/v1/support /portal-files/test; do
    code=$(curl --silent --show-error --max-time 10 -o /dev/null -w '%{http_code}' "$portal$path")
    [[ "$code" == 503 ]] || die 'Maintenance guard did not refuse a business route.'
  done
  code=$(curl --silent --show-error --max-time 10 -X POST -o /dev/null -w '%{http_code}' "$portal/health/readiness")
  [[ "$code" == 503 ]] || die 'Maintenance guard allowed a mutating request.'
  curl --fail --silent --show-error --max-time 10 "$portal/health/readiness" | check_readiness
  actual=$(curl --fail --silent --show-error --max-time 10 "$portal/login" | hash)
  [[ "$actual" == "$expected" ]] || die 'Guarded frontend identity mismatch.'
  actual=$(curl --fail --silent --show-error --max-time 10 "$portal$asset" | hash)
  [[ "$actual" == "$expected_asset" ]] || die 'Guarded asset identity mismatch.'
  actual=$(curl --fail --silent --show-error --max-time 10 "$portal/sw.js" | hash)
  [[ "$actual" == "$expected_worker" ]] || die 'Guarded service-worker identity mismatch.'
}
forward_wait_beat() {
  local id started start=$SECONDS
  id=$(compose "$candidate" ps -q celery_beat)
  started=$(docker inspect --format '{{.State.StartedAt}}' "$id")
  while true; do
    [[ "$(docker inspect --format '{{.State.Running}} {{.State.StartedAt}}' "$id")" == "true $started" ]] || return 1
    if docker logs --since "$started" "$id" 2>&1 | python3 -c '
import json,sys
for line in sys.stdin:
 try:r=json.loads(line)
 except ValueError:continue
 if isinstance(r,dict) and r.get("logger")=="celery.beat" and r.get("message")=="beat: Starting...":sys.exit(0)
sys.exit(1)
'; then return 0; fi
    (( SECONDS-start < 60 )) || return 1
    sleep 1
  done
}
forward_release() {
  [[ "$current" == 202605310093 && "$heads" == 202605310097 && "$runtime_changed" == 1 ]] || die 'Forward mode only supports exact093 to097.'
  forward_permit validate
  forward_inventory
  forward_prepare_guard
  runtime_attempted=1
  ( set -o noclobber; printf 'Forward093-to097 in progress; no secured-backup guarantee.\n' > "$state/forward097.attempt" ) || die 'Attempt already exists.'
  python3 - "$state/forward097.attempt" "$state" <<'PY'
import os,sys
for path in sys.argv[1:]:
 fd=os.open(path,os.O_RDONLY);os.fsync(fd);os.close(fd)
PY
  forward_warm_stop nginx || die 'Ingress did not stop gracefully.'
  forward_warm_stop celery_beat || die 'Scheduler did not stop gracefully.'
  forward_idle || die 'In-flight worker tasks did not drain.'
  forward_warm_stop celery_worker || die 'Worker did not stop gracefully.'
  forward_warm_stop backend || die 'Backend did not stop gracefully.'
  [[ "$(forward_clients)" == 0 && "$(forward_schema)" == 202605310093 ]] || die 'Writer/schema preflight failed.'
  forward_data_check
  verify_main; verify_ci; verify_deploy_run
  forward_inventory
  [[ "$(forward_clients)" == 0 && "$(forward_schema)" == 202605310093 ]] || die 'Final writer/schema preflight failed.'
  forward_permit consume
  forward_mark permit_consumed_before_migration
  compose "$candidate" run --rm --no-deps --pull never -T backend alembic upgrade 202605310097
  current=$(forward_schema)
  [[ "$current" == 202605310097 ]] || die 'Forward migration did not reach097.'
  forward_verify_schema
  forward_mark schema097_verified
  frontend_attempted=1
  publish_frontend "$frontend_image"
  forward_compose "$candidate" up --detach --no-build --pull never --no-deps --wait --wait-timeout 150 backend nginx
  [[ "$(docker inspect --format '{{.Image}}' "$(compose "$candidate" ps -q backend)")" == "$backend_id" ]] || die 'Wrong backend image.'
  forward_smoke
  forward_mark guarded_smoke_verified
  forward_mark guarded_verification_pending
}
# Called only after durable outer verification and current-pointer checkpoint.
forward_reopen() {
  [[ "$(readlink -f "$state/current")" == "$candidate" ]] || die 'Uncommitted candidate cannot reopen.'
  [[ -f "$candidate/FORWARD_VERIFIED" ]] || die 'Missing durable verified checkpoint.'
  compose "$candidate" up --detach --no-build --pull never --no-deps --wait --wait-timeout 150 celery_worker celery_beat
  forward_wait_beat || die 'Scheduler startup not observed.'
  local service container
  for service in celery_worker celery_beat; do
    container=$(compose "$candidate" ps -q "$service")
    [[ -n "$container" ]] || die 'Missing reopened writer.'
    [[ "$(docker inspect --format '{{.Image}} {{.State.Running}}' "$container")" == "$backend_id true" ]] || die 'Reopened writer identity/state mismatch.'
  done
  docker exec "$(compose "$candidate" ps -q celery_worker)" celery -A app.tasks.celery_app.celery_app inspect ping --json --timeout=3 | python3 -c '
import json,sys
r=json.load(sys.stdin)
if not isinstance(r,dict) or len(r)!=1 or any(v!={"ok":"pong"} for v in r.values()):sys.exit("Worker health not verified")
'
  forward_inventory
  forward_smoke
  python3 - "$state" "$candidate" "$sha" "$run_id" "$ci_attempt" "$deploy_run_id" "$deploy_attempt" <<'PYCOMMIT'
import json,os,sys
from pathlib import Path
state,candidate=map(Path,sys.argv[1:3])
if (state/'current').resolve()!=candidate or not (candidate/'FORWARD_VERIFIED').is_file():
    raise SystemExit('Candidate checkpoint mismatch')
record=dict(zip(('sha','ci_run','ci_attempt','deploy_run','deploy_attempt'),sys.argv[3:]))
record.update(candidate=str(candidate),schema='202605310097',state='verified-serving-committed',receipt='pending-observed-reopen')
fd=os.open(state/'forward097.reopen-commit',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
try:
    os.write(fd,(json.dumps(record,sort_keys=True)+'\n').encode());os.fsync(fd)
finally:os.close(fd)
fd=os.open(state,os.O_RDONLY)
try:os.fsync(fd)
finally:os.close(fd)
PYCOMMIT
  forward_mark reopening_authorized_after_writer_verification
  forward_mark writers_started_after_checkpoint
  compose "$candidate" up --detach --no-build --pull never --no-deps --wait --wait-timeout 150 nginx
  forward_mark ingress_reopened
}
