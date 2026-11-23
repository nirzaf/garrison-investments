#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

[[ "$EUID" == 0 && "${SUDO_USER:-}" == garrison-gh-deploy ]] ||
  die 'The hosted deployment entrypoint must be called through its dedicated SSH identity.'
[[ "$#" == 0 ]] || die 'The root-controlled deployment helper accepts no command-line arguments.'

IFS= read -r ci_run_id || die 'Missing CI run ID.'
IFS= read -r release_sha || die 'Missing release SHA.'
IFS= read -r deployment_run_id || die 'Missing deployment run ID.'
IFS= read -r deployment_attempt || die 'Missing deployment attempt.'
IFS= read -r release_mode || die 'Missing release mode.'
IFS= read -r token || die 'Missing GitHub API token.'

[[ "$ci_run_id" =~ ^[1-9][0-9]*$ && "$release_sha" =~ ^[a-f0-9]{40}$ &&
   "$deployment_run_id" =~ ^[1-9][0-9]*$ && "$deployment_attempt" =~ ^[1-9][0-9]*$ &&
   "$token" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'Invalid release payload.'
case "$release_mode" in
  technical-checks-v1|pinned-no-backup-093|forward-only-093-to-097|incident-replacement|postgres19-maintenance|postgres19-maintenance-retry) ;;
  *) die 'Unsupported release mode.' ;;
esac
if IFS= read -r trailing || [[ -n "$trailing" ]]; then
  die 'Unexpected trailing release payload.'
fi

release_entrypoint=/usr/local/sbin/garrison-deploy
[[ -f "$release_entrypoint" && ! -L "$release_entrypoint" && -O "$release_entrypoint" && -x "$release_entrypoint" ]] ||
  die 'The root-controlled production release entrypoint is unavailable.'
mode=$(stat -c '%a' "$release_entrypoint")
(( (8#$mode & 022) == 0 )) || die 'The production release entrypoint is writable by a non-root identity.'

printf '%s\n%s\n%s\n' "$token" "$deployment_run_id" "$deployment_attempt" |
  "$release_entrypoint" "$ci_run_id" "$release_sha" rollback-v2 "$release_mode"
