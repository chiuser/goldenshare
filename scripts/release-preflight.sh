#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_WEB_TESTS="${RUN_WEB_TESTS:-1}"
RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-1}"
RUN_COMPILE_CHECK="${RUN_COMPILE_CHECK:-1}"
RUN_MINIMAL_TESTS="${RUN_MINIMAL_TESTS:-1}"
RUN_ARCH_TESTS="${RUN_ARCH_TESTS:-1}"
RUN_ENTRYPOINT_SMOKE="${RUN_ENTRYPOINT_SMOKE:-1}"
RUN_LEGACY_COMPILE="${RUN_LEGACY_COMPILE:-1}"

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

  if [[ "${RUN_MINIMAL_TESTS}" == "1" || "${RUN_WEB_TESTS}" == "1" || "${RUN_ARCH_TESTS}" == "1" ]]; then
    require_cmd pytest
  fi
  if [[ "${RUN_FRONTEND_BUILD}" == "1" ]]; then
    require_cmd npm
  fi

  log "发版预检开始"

  if [[ "${RUN_COMPILE_CHECK}" == "1" ]]; then
    log "1/6 Python 编译检查"
    compile_targets=(src/foundation src/ops src/biz src/app src/shared src/scripts)
    if [[ "${RUN_LEGACY_COMPILE}" == "1" ]]; then
      compile_targets+=(src/platform src/operations)
    fi
    python3 -m compileall "${compile_targets[@]}"
  fi

  if [[ "${RUN_ENTRYPOINT_SMOKE}" == "1" ]]; then
    log "2/6 Web 运行入口冒烟检查"
    python3 -m src.app.web.run --help >/dev/null
  fi

  if [[ "${RUN_MINIMAL_TESTS}" == "1" ]]; then
    log "3/6 最小回归测试"
    pytest -q tests/web/test_health_api.py tests/web/test_quote_api.py
  fi

  if [[ "${RUN_WEB_TESTS}" == "1" ]]; then
    log "4/6 Web 关键测试"
    pytest -q \
      tests/web/test_auth_api.py \
      tests/web/test_admin_api.py \
      tests/web/test_ops_overview_api.py \
      tests/web/test_ops_execution_api.py \
      tests/web/test_ops_schedule_api.py \
      tests/web/test_ops_runtime_api.py
  fi

  if [[ "${RUN_ARCH_TESTS}" == "1" ]]; then
    log "5/6 架构边界测试"
    pytest -q \
      tests/architecture/test_subsystem_dependency_matrix.py \
      tests/architecture/test_virtual_split_boundaries.py
  fi

  if [[ "${RUN_FRONTEND_BUILD}" == "1" ]]; then
    log "6/6 前端构建检查"
    npm --prefix frontend run build
  fi

  log "发版预检通过"
}

main "$@"
