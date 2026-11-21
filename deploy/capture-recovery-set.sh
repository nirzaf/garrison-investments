#!/bin/bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077

base=/opt/garrison-portal
state="$base/deploy"
recovery="$base/recovery/scheduled"
project=garrison-portal

die() { printf '%s\n' "$*" >&2; exit 1; }

private_file() {
  [[ "$1" == /* && -f "$1" && ! -L "$1" && "$(stat -c %u "$1")" == 0 ]] ||
    die 'Recovery inputs must be absolute root-owned regular files.'
  local mode
  mode=$(stat -c %a "$1")
  (( (8#$mode & 077) == 0 )) || die 'Recovery inputs require owner-only permissions.'
}

protected_directory() {
  local directory=$1 forbidden=$2 mode
  [[ -d "$directory" && ! -L "$directory" && "$(stat -c %u "$directory")" == 0 ]] || return 1
  mode=$(stat -c %a "$directory") || return 1
  (( (8#$mode & forbidden) == 0 ))
}

policy=${RECOVERY_POLICY:?Set the approved recovery policy file path.}
template=${RECOVERY_CAPTURE_TEMPLATE:?Set the approved capture inventory path.}
configuration=${RECOVERY_CONFIGURATION_ROOT:?Set the dedicated nonsecret configuration directory.}
capture_env=${RECOVERY_CAPTURE_ENV:?Set the dedicated capture credentials file path.}
publisher_env=${RECOVERY_PUBLISH_ENV:?Set the dedicated publisher credentials file path.}
auth_key=${BACKUP_AUTH_KEY_FILE:?Set the restricted authentication key file path.}
backup_password_file=${BACKUP_ENCRYPTION_PASSWORD_HOST_FILE:?Set the root-only backup-encryption file path.}
key_id=${BACKUP_AUTH_KEY_ID:?Set the approved authentication key identifier.}
[[ "$key_id" =~ ^[a-zA-Z0-9_.-]{1,80}$ ]] || die 'Invalid authentication key ID.'
[[ "$configuration" == /* && -d "$configuration" && ! -L "$configuration" &&
   "$(stat -c %u "$configuration")" == 0 ]] || die 'Configuration requires a root-owned directory.'
configuration=$(realpath -e -- "$configuration")
[[ "$configuration" != / ]] || die 'Configuration requires a dedicated directory.'
for input in "$policy" "$template" "$capture_env" "$publisher_env" "$auth_key" "$backup_password_file"; do
  private_file "$input"
  [[ "$(realpath -e -- "$input")" != "$configuration/"* ]] ||
    die 'Keep recovery control files and credentials outside the configuration directory.'
done
[[ "$capture_env" != "$publisher_env" ]] || die 'Capture and publisher need separate credentials.'
[[ "$(stat -c %s "$auth_key")" == 32 ]] || die 'Authentication key must be exactly 32 bytes.'
python3 - "$capture_env" "$publisher_env" <<'PY'
import re
import sys
from pathlib import Path

error = "Capture and publisher credential inputs must be explicit and isolated."

def assignments(path):
    entries = {}
    with Path(path).open(encoding="utf-8-sig", newline="\n") as environment:
        lines = environment.read().split("\n")
    for raw in lines:
        line = raw.lstrip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in entries:
            sys.exit(error)
        entries[name] = value
    return entries

capture, publish = (assignments(path) for path in sys.argv[1:])
source = {"DATABASE_URL", "MINIO_ENDPOINT", "MINIO_BUCKET", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD",
          "BACKUP_ENCRYPTION_PASSWORD_FILE"}
legacy = {"BACKUP_ENCRYPTION_PASSWORD", "BACKUP_ENCRYPTION_PASSWORD_HOST_FILE"}
destination = {"DR_BACKUP_ENDPOINT", "DR_BACKUP_BUCKET", "DR_BACKUP_PREFIX", "DR_BACKUP_SECURE",
               "DR_BACKUP_ACCESS_KEY", "DR_BACKUP_SECRET_KEY"}
source_only = source | legacy | {"BACKUP_GRAFANA_DATABASE_URL", "MINIO_SECURE"}
if (
    not all(capture.get(name, "").strip() for name in source)
    or capture.get("BACKUP_ENCRYPTION_PASSWORD_FILE") != "/run/secrets/backup_encryption_password"
    or not all(publish.get(name, "").strip() for name in destination)
    or source_only & publish.keys()
    or destination & capture.keys()
):
    sys.exit(error)
PY

exec 9>>"$state/deploy.lock"
flock -n 9 || die 'The deployment or maintenance lock is held.'
release=$(readlink -f "$state/current")
[[ "$release" == "$base/releases/"* && -f "$release/SOURCE_COMMIT" ]] ||
  die 'The active release identity is unavailable.'
sha=$(cat "$release/SOURCE_COMMIT")
[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || die 'Invalid active release SHA.'
backend="$project-backend-1"
image=$(docker inspect --format '{{.Image}}' "$backend")
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ ]] || die 'Active backend image identity is unavailable.'
protected_directory "$base" 022 || die 'Recovery requires a protected root-owned portal directory.'
recovery_parent=${recovery%/*}
if [[ ! -e "$recovery_parent" && ! -L "$recovery_parent" ]]; then mkdir -m 0700 -- "$recovery_parent"; fi
protected_directory "$recovery_parent" 022 || die 'Recovery requires a protected root-owned directory.'
if [[ ! -e "$recovery" && ! -L "$recovery" ]]; then mkdir -m 0700 -- "$recovery"; fi
protected_directory "$recovery" 077 || die 'Scheduled recovery requires an owner-only root directory.'

# Use one owned slot. A publication failure must not allocate another full set.
run="$recovery/.scheduled-capture"
started_at=$(date -u +%FT%TZ)
phase=preflight
# Bound status reporting even when the policy limits are unavailable.
status_timeout=60
created=0
paused=0
writers=()
common=(-v "$policy:/policy.json:ro" -v "$auth_key:/recovery-key:ro"
  -e BACKUP_AUTH_KEY_FILE=/recovery-key -e "BACKUP_AUTH_KEY_ID=$key_id")
capture_secret=(-v "$backup_password_file:/run/secrets/backup_encryption_password:ro")
remove_run() {
  protected_directory "$run" 077 && rm -rf -- "$run"
}
resume_writers() {
  if (( paused && ${#writers[@]} )); then
    local service writer status failed=0 end=$((SECONDS + 90))
    local started=() pending=()
    for service in backend grafana celery_worker celery_beat nginx; do
      writer="$project-$service-1"
      if ! printf '%s\n' "${writers[@]}" | grep -Fxq "$writer"; then continue; fi
      if timeout 10 docker start "$writer" >/dev/null; then
        started+=("$writer")
      else
        failed=1
      fi
    done
    while (( ${#started[@]} )); do
      pending=()
      for writer in "${started[@]}"; do
        status=$(timeout 5 docker inspect --format '{{if .State.Running}}{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}{{else}}stopped{{end}}' "$writer") || status=unavailable
        case "$status" in
          healthy|running) ;;
          starting) pending+=("$writer") ;;
          *) failed=1 ;;
        esac
      done
      (( ${#pending[@]} )) || break
      (( SECONDS < end )) || return 1
      started=("${pending[@]}")
      sleep 1
    done
    (( failed == 0 )) || return 1
  fi
  paused=0
}
finish() {
  local status=$?
  trap - EXIT
  if ! resume_writers; then
    phase=resume
    status=1
  elif (( created )) && [[ -d "$run" && ! -e "$run/set/manifest.json" && ! -L "$run/set/manifest.json" ]]; then
    if ! remove_run; then
      phase=cleanup
      status=1
    fi
  fi
  python3 - "$recovery" "$sha" "$started_at" "$phase" "$status" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

root, sha, started_at, phase, exit_status = sys.argv[1:]
record = {
    "source_sha": sha,
    "started_at_utc": started_at,
    "completed_at_utc": datetime.now(UTC).isoformat(),
    "phase": phase,
    "outcome": "pass" if exit_status == "0" else "fail",
}
with NamedTemporaryFile(mode="w", dir=root, prefix=".attempt-", delete=False) as output:
    json.dump(record, output, sort_keys=True)
Path(output.name).replace(Path(root) / "last-attempt.json")
PY
  if ! timeout "$status_timeout" docker run --rm --env-file "$publisher_env" \
    "${common[@]}" -v "$recovery/last-attempt.json:/receipts/last-attempt.json:ro" \
    -v "$template:/capture-inventory.json:ro" "$image" \
    python -m scripts.backup_set publish-attempt /receipts/last-attempt.json \
    --policy /policy.json --inventory /capture-inventory.json; then
    printf '%s\n' 'Scheduled recovery attempt was recorded locally but status publication failed.' >&2
    (( status != 0 )) || status=1
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 1' INT TERM

limits=$(timeout 30 docker run --rm --network none -v "$policy:/policy.json:ro" "$image" \
  python -m scripts.backup_set policy-check --policy /policy.json) &&
  [[ "$limits" =~ ^([1-9][0-9]*)\ ([1-9][0-9]*)$ ]] ||
  die 'Approved recovery time limits could not be read.'
pause_seconds=${BASH_REMATCH[1]}
publish_minutes=${BASH_REMATCH[2]}
status_timeout=$((publish_minutes * 60))
phase=spool

publish_capture() {
  protected_directory "$run/set" 077 || die 'Pending recovery set is not a private directory.'
  private_file "$run/set/manifest.json"
  phase=publication
  timeout "$((publish_minutes * 60))" docker run --rm --env-file "$publisher_env" \
    "${common[@]}" -v "$run/set:/capture:ro" -v "$recovery:/receipts" "$image" \
    python -m scripts.backup_set publish /capture --policy /policy.json \
    --receipt /receipts/latest-success.json
  phase=cleanup
  remove_run || die 'Published recovery workspace could not be removed safely.'
  phase=complete
}

if [[ -e "$run" || -L "$run" ]]; then
  protected_directory "$run" 077 || die 'Pending recovery workspace is not a private directory.'
  private_file "$run/attempt"
  [[ -f "$run/writers-resumed" && ! -L "$run/writers-resumed" ]] ||
    die 'Pending recovery workspace requires operator review before reuse.'
  private_file "$run/writers-resumed"
  read -r capture_sha capture_image capture_started extra < "$run/attempt"
  [[ "$capture_sha" == "$sha" && "$capture_image" == "$image" && -z "$extra" &&
     "$capture_started" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] ||
    die 'Pending recovery capture differs from the active release or has invalid metadata.'
  # The receipt covers the original snapshot and its eventual verified publication.
  started_at=$capture_started
  publish_capture
  exit 0
fi

network=$(docker inspect --format '{{range $name, $value := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$project-postgres-1")
[[ "$network" =~ ^[a-zA-Z0-9_-]+$ ]] || die 'Expected one private database network.'
mkdir -m 0700 -- "$run"
created=1
printf '%s %s %s\n' "$sha" "$image" "$started_at" > "$run/attempt"

for service in nginx celery_beat celery_worker backend grafana; do
  writer="$project-$service-1"
  running=$(docker inspect --format '{{.State.Running}}' "$writer")
  [[ "$running" == false || "$running" == true ]] || die 'Writer state is unavailable.'
  if [[ "$running" == true ]]; then writers+=("$writer"); fi
done
phase=quiescence
pause_started=$SECONDS
paused_at=$(date -u +%FT%TZ)
paused=1
if (( ${#writers[@]} )); then
  timeout "$pause_seconds" docker stop "${writers[@]}" >/dev/null
fi
for writer in "${writers[@]}"; do
  [[ "$(docker inspect --format '{{.State.Running}}' "$writer")" == false ]] ||
    die 'A recovery writer is still running.'
done
python3 - "$template" "$run/capture-receipt.json" "$sha" "$image" "$paused_at" <<'PY'
import json
import sys
from pathlib import Path

template, output, sha, image, paused_at = sys.argv[1:]
with open(template, encoding="utf-8") as source:
    capture = json.load(source)
if capture.get("source_sha") != sha or capture.get("image_digests", {}).get("backend") != image:
    sys.exit("Capture inventory differs from the active release or backend image.")
capture.update(quiescence_started_at_utc=paused_at, writers_paused=True)
Path(output).write_text(json.dumps(capture), encoding="utf-8")
PY

remaining=$((pause_seconds - (SECONDS - pause_started)))
(( remaining > 0 )) || die 'The capture pause limit was exceeded.'
phase=capture
timeout "$remaining" docker run --rm --network "$network" --env-file "$capture_env" \
  "${common[@]}" "${capture_secret[@]}" -v "$run:/capture" \
  -v "$configuration:/configuration:ro" "$image" \
  python -m scripts.backup_set capture --destination /capture/set --source-sha "$sha" \
  --policy /policy.json --capture-receipt /capture/capture-receipt.json \
  --configuration-root /configuration --consistency-note "Deployment lock and writer pause at $paused_at"
phase=resume
resume_writers || die 'Previously running writers could not be resumed.'
(( SECONDS - pause_started <= pause_seconds )) || die 'The approved capture pause was exceeded.'
: > "$run/writers-resumed"
publish_capture
