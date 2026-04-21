#!/usr/bin/env bash
set -Eeuo pipefail

SSH_TARGET="${SSH_TARGET:-goldenshare-prod}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-/etc/goldenshare/web.env}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/remote-web-env.sh [--host <ssh_host>] [--file <remote_file>] <command> [args]

Commands:
  show
      Show full env file with line numbers.

  get <KEY>
      Show one key with line number, e.g. USE_SYNC_V2_DATASETS.

  set <KEY> <VALUE>
      Upsert one key to the specified value.

  unset <KEY>
      Remove one key from the file.

Examples:
  bash scripts/remote-web-env.sh show
  bash scripts/remote-web-env.sh get USE_SYNC_V2_DATASETS
  bash scripts/remote-web-env.sh set USE_SYNC_V2_DATASETS stk_factor_pro
  bash scripts/remote-web-env.sh unset USE_SYNC_V2_DATASETS

Notes:
  - This script always uses: ssh <host> + sudo -n + /etc/goldenshare/web.env
  - On sudo permission issues, it exits immediately (no fallback guessing).
EOF
}

fail() {
  echo "[remote-web-env] $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

validate_key() {
  local key="${1:-}"
  [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail "invalid key: ${key}"
}

run_remote_script() {
  local script="$1"
  shift
  local quoted_args=""
  local arg=""
  for arg in "$@"; do
    quoted_args+=" $(printf '%q' "${arg}")"
  done
  ssh "${SSH_TARGET}" "sudo -n /bin/bash -s --${quoted_args}" <<<"${script}"
}

cmd_show() {
  run_remote_script '
set -Eeuo pipefail
file="$1"
nl -ba "$file"
' "${REMOTE_ENV_FILE}"
}

cmd_get() {
  local key="${1:-}"
  validate_key "${key}"
  run_remote_script '
set -Eeuo pipefail
file="$1"
key="$2"
grep -n "^${key}=" "$file"
' "${REMOTE_ENV_FILE}" "${key}"
}

cmd_set() {
  local key="${1:-}"
  local value="${2:-}"
  validate_key "${key}"
  run_remote_script '
set -Eeuo pipefail
file="$1"
key="$2"
value="$3"
if grep -q "^${key}=" "$file"; then
  escaped_value="${value//\\/\\\\}"
  escaped_value="${escaped_value//&/\\&}"
  escaped_value="${escaped_value//|/\\|}"
  sed -i "s|^${key}=.*|${key}=${escaped_value}|" "$file"
else
  printf "%s=%s\n" "$key" "$value" >> "$file"
fi
grep -n "^${key}=" "$file"
' "${REMOTE_ENV_FILE}" "${key}" "${value}"
}

cmd_unset() {
  local key="${1:-}"
  validate_key "${key}"
  run_remote_script '
set -Eeuo pipefail
file="$1"
key="$2"
if grep -q "^${key}=" "$file"; then
  sed -i "/^${key}=.*/d" "$file"
fi
if grep -q "^${key}=" "$file"; then
  echo "failed to remove key: ${key}" >&2
  exit 1
fi
echo "removed: ${key}"
' "${REMOTE_ENV_FILE}" "${key}"
}

parse_opts() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --host)
        shift
        [[ $# -gt 0 ]] || fail "missing value for --host"
        SSH_TARGET="$1"
        ;;
      --file)
        shift
        [[ $# -gt 0 ]] || fail "missing value for --file"
        REMOTE_ENV_FILE="$1"
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        break
        ;;
    esac
    shift
  done
  ARGS=("$@")
}

main() {
  require_cmd ssh
  parse_opts "$@"
  [[ ${#ARGS[@]} -gt 0 ]] || {
    usage
    exit 1
  }

  local command="${ARGS[0]}"
  case "${command}" in
    show)
      [[ ${#ARGS[@]} -eq 1 ]] || fail "show does not accept extra arguments"
      cmd_show
      ;;
    get)
      [[ ${#ARGS[@]} -eq 2 ]] || fail "usage: get <KEY>"
      cmd_get "${ARGS[1]}"
      ;;
    set)
      [[ ${#ARGS[@]} -eq 3 ]] || fail "usage: set <KEY> <VALUE>"
      cmd_set "${ARGS[1]}" "${ARGS[2]}"
      ;;
    unset)
      [[ ${#ARGS[@]} -eq 2 ]] || fail "usage: unset <KEY>"
      cmd_unset "${ARGS[1]}"
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      fail "unknown command: ${command}"
      ;;
  esac
}

ARGS=()
main "$@"

