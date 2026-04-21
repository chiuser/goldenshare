#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env.web.local}"
PSQL_BIN="${PSQL_BIN:-psql}"

SQL_CMD=""
SQL_FILE=""
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
Usage:
  bash scripts/psql-remote.sh [options] [-- <extra psql args>]

Description:
  Uses DATABASE_URL from .env.web.local to connect to the remote Postgres database.
  Supports one-shot SQL, SQL file execution, stdin piping, and interactive psql.

Options:
  -c, --command <sql>      Execute one SQL statement and exit.
  -f, --file <path>        Execute SQL from a file and exit.
  --env-file <path>        Override env file path (default: .env.web.local).
  -h, --help               Show this help.

Examples:
  bash scripts/psql-remote.sh -c "select 1;"
  bash scripts/psql-remote.sh -f /tmp/check.sql
  cat /tmp/check.sql | bash scripts/psql-remote.sh
  bash scripts/psql-remote.sh
EOF
}

fail() {
  echo "[psql-remote] $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -c|--command)
        local opt="$1"
        shift
        [[ $# -gt 0 ]] || fail "missing value for ${opt}"
        [[ -z "${SQL_FILE}" ]] || fail "--command and --file cannot be used together"
        SQL_CMD="$1"
        ;;
      -f|--file)
        local opt="$1"
        shift
        [[ $# -gt 0 ]] || fail "missing value for ${opt}"
        [[ -z "${SQL_CMD}" ]] || fail "--command and --file cannot be used together"
        SQL_FILE="$1"
        ;;
      --env-file)
        shift
        [[ $# -gt 0 ]] || fail "missing value for --env-file"
        ENV_FILE="$1"
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      --)
        shift
        while [[ $# -gt 0 ]]; do
          EXTRA_ARGS+=("$1")
          shift
        done
        break
        ;;
      *)
        EXTRA_ARGS+=("$1")
        ;;
    esac
    shift
  done
}

main() {
  parse_args "$@"

  require_cmd "${PSQL_BIN}"
  [[ -f "${ENV_FILE}" ]] || fail "env file not found: ${ENV_FILE}"

  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a

  [[ -n "${DATABASE_URL:-}" ]] || fail "DATABASE_URL is empty in ${ENV_FILE}"

  # psql does not support SQLAlchemy dialect suffixes such as postgresql+psycopg.
  local db_url="${DATABASE_URL/postgresql+psycopg/postgresql}"

  local cmd=("${PSQL_BIN}" "${db_url}" "-X" "-v" "ON_ERROR_STOP=1")

  if [[ -n "${SQL_CMD}" ]]; then
    cmd+=("-c" "${SQL_CMD}")
  elif [[ -n "${SQL_FILE}" ]]; then
    [[ -f "${SQL_FILE}" ]] || fail "sql file not found: ${SQL_FILE}"
    cmd+=("-f" "${SQL_FILE}")
  fi

  if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
    cmd+=("${EXTRA_ARGS[@]}")
  fi

  "${cmd[@]}"
}

main "$@"
