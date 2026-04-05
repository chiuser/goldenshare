#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_WEB_TESTS="${RUN_WEB_TESTS:-1}"
RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-1}"
RUN_COMPILE_CHECK="${RUN_COMPILE_CHECK:-1}"
RUN_MINIMAL_TESTS="${RUN_MINIMAL_TESTS:-1}"
RUN_ARCH_TESTS="${RUN_ARCH_TESTS:-1}"

log() {
  echo "[$(date '+%F %T')] $*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "缺少命令: $1"
    exit 1
  }
}

main() {
  cd "${ROOT_DIR}"
  require_cmd python3
  require_cmd pytest
  require_cmd npm

  log "发版预检开始"

  if [[ "${RUN_COMPILE_CHECK}" == "1" ]]; then
    log "1/5 Python 编译检查"
    python3 -m compileall src/foundation src/ops src/biz src/platform src/operations src/shared src/scripts
  fi

  if [[ "${RUN_MINIMAL_TESTS}" == "1" ]]; then
    log "2/5 最小回归测试"
    pytest -q tests/web/test_health_api.py tests/web/test_quote_api.py
  fi

  if [[ "${RUN_WEB_TESTS}" == "1" ]]; then
    log "3/5 Web 关键测试"
    pytest -q \
      tests/web/test_auth_api.py \
      tests/web/test_admin_api.py \
      tests/web/test_ops_overview_api.py \
      tests/web/test_ops_execution_api.py \
      tests/web/test_ops_schedule_api.py \
      tests/web/test_ops_runtime_api.py
  fi

  if [[ "${RUN_ARCH_TESTS}" == "1" ]]; then
    log "4/5 架构边界测试"
    pytest -q tests/architecture/test_virtual_split_boundaries.py
  fi

  if [[ "${RUN_FRONTEND_BUILD}" == "1" ]]; then
    log "5/5 前端构建检查"
    npm --prefix frontend run build
  fi

  log "发版预检通过"
}

main "$@"
