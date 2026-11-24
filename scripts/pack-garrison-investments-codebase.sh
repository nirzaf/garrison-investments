#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/pack-garrison-investments-codebase.sh [--output PATH] [--compress]

Pack this Garrison Investments checkout into a Markdown file with Repomix.

Options:
  -o, --output PATH  Output file. Relative paths are resolved from the
                     directory where the command is run.
                     Default: ../repomix/garrison-investments-codebase.md
      --compress     Create a smaller structural overview. The default
                     keeps full source content for detailed reviews.
  -h, --help         Show this help.

The default output is outside the repository. Review the generated file for
sensitive content before sharing it with an external service.
EOF
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
default_output="$(dirname "$repo_root")/repomix/garrison-investments-codebase.md"
output_path="$default_output"
compress=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    -o|--output)
      if [ "$#" -lt 2 ] || [ -z "$2" ]; then
        printf 'Error: %s requires a file path.\n' "$1" >&2
        usage >&2
        exit 2
      fi
      output_path="$2"
      shift 2
      ;;
    --compress)
      compress=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Error: unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# Prefer an NVM-managed Repomix and its matching Node runtime when both it and
# Homebrew's Repomix are on PATH.
IFS=: read -r -a path_entries <<< "$PATH"
for candidate_bin in "${path_entries[@]}"; do
  case "$candidate_bin" in
    */.nvm/versions/node/*/bin)
      if [ -x "$candidate_bin/node" ] && [ -x "$candidate_bin/repomix" ]; then
        PATH="$candidate_bin:$PATH"
        export PATH
        break
      fi
      ;;
  esac
done

if ! command -v repomix >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Error: Repomix is not installed or is not on PATH.
Install it with `npm install -g repomix` or `brew install repomix`.
EOF
  exit 127
fi

case "$output_path" in
  /*) ;;
  *) output_path="$PWD/$output_path" ;;
esac

# Extend .gitignore with local configuration, key material, runtime data, and
# build/cache paths that should not be included in a codebase handoff.
ignore_patterns='**/.env*,**/*.pem,**/*.key,**/*.p12,**/*.pfx,**/id_rsa*,**/id_ed25519*,**/nginx/ssl/**,**/storage/**,**/backups/**,**/node_modules/**,**/dist/**,**/build/**,**/.venv/**,**/__pycache__/**,**/.pytest_cache/**,**/.ruff_cache/**,**/.mypy_cache/**,**/graphify-out/**,**/garrison-investments-codebase.md'

case "$output_path" in
  "$repo_root"/*)
    printf 'Warning: output is inside the repository; it is excluded from this pack but may be committed unless ignored.\n' >&2
    relative_output="${output_path#"$repo_root"/}"
    ignore_patterns="$ignore_patterns,$relative_output"
    ;;
esac

mkdir -p "$(dirname "$output_path")"

repomix_args=(
  "$repo_root"
  --style markdown
  --output "$output_path"
  --output-show-line-numbers
  --ignore "$ignore_patterns"
)

if [ "$compress" = true ]; then
  repomix_args+=(--compress)
fi

printf 'Packing %s\nOutput: %s\n' "$repo_root" "$output_path"
printf 'Repomix: %s\n' "$(command -v repomix)"
repomix "${repomix_args[@]}"
