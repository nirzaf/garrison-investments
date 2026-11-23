#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/bin:/bin
umask 077

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

command=${SSH_ORIGINAL_COMMAND:-}
if [[ "$command" == probe ]]; then
  printf '%s\n' 'restricted deployment transport ready'
  exit 0
fi

release_pattern='^release ([1-9][0-9]*) ([a-f0-9]{40}) ([1-9][0-9]*) ([1-9][0-9]*) ([a-z0-9-]+)$'
[[ "$command" =~ $release_pattern ]] || die 'Only probe or a valid release command is accepted.'
ci_run_id=${BASH_REMATCH[1]}
release_sha=${BASH_REMATCH[2]}
deployment_run_id=${BASH_REMATCH[3]}
deployment_attempt=${BASH_REMATCH[4]}
release_mode=${BASH_REMATCH[5]}
case "$release_mode" in
  technical-checks-v1|pinned-no-backup-093|forward-only-093-to-097|incident-replacement|postgres19-maintenance|postgres19-maintenance-retry) ;;
  *) die 'Unsupported release mode.' ;;
esac

{
  printf '%s\n' "$ci_run_id" "$release_sha" "$deployment_run_id" "$deployment_attempt" "$release_mode"
  cat
} | /usr/bin/sudo -n /usr/local/sbin/garrison-gh-release-root
