#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ENV_FILE="${ENV_FILE:-.env.web.local}"
WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

RUN_BACKEND_COMPILE="${RUN_BACKEND_COMPILE:-1}"
RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-1}"
RUN_PREFLIGHT="${RUN_PREFLIGHT:-0}"
INSTALL_PY_DEPS="${INSTALL_PY_DEPS:-0}"
INSTALL_FE_DEPS="${INSTALL_FE_DEPS:-0}"

START_WEB=1
START_FRONTEND=1

WEB_PID=""
FRONTEND_PID=""

log() {
  echo "[$(date '+%F %T')] $*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "缺少命令: $1"
    exit 1
  }
}

usage() {
  cat <<'EOF'
用法:
  bash scripts/local-build-and-run.sh [options]

说明:
  本地一键执行“编译 + 启动”流程：
  1) 后端编译检查（compileall）
  2) 前端构建（npm run build）
  3) 启动 Web 与前端 dev server

选项:
  --env-file <path>            指定 Web 环境文件（默认 .env.web.local）
  --web-host <host>            Web 监听地址（默认 127.0.0.1）
  --web-port <port>            Web 端口（默认 8000）
  --frontend-host <host>       前端 dev server 地址（默认 127.0.0.1）
  --frontend-port <port>       前端 dev server 端口（默认 5173）
  --web-only                   仅启动 Web（不启动前端）
  --frontend-only              仅启动前端（不启动 Web）
  --skip-backend-compile       跳过后端编译检查
  --skip-frontend-build        跳过前端构建
  --with-preflight             先执行 scripts/release-preflight.sh
  --install-python-deps        执行 python3 -m pip install -e .
  --install-frontend-deps      执行 npm --prefix frontend install
  -h, --help                   显示帮助

示例:
  bash scripts/local-build-and-run.sh
  bash scripts/local-build-and-run.sh --web-only
  bash scripts/local-build-and-run.sh --env-file .env.web.local --web-port 8001
EOF
}

stop_pid() {
  local pid="$1"
  local name="$2"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    log "停止 ${name}（pid=${pid}）"
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
  fi
}

cleanup() {
  local code="${1:-0}"
  trap - EXIT INT TERM
  stop_pid "${WEB_PID}" "Web"
  stop_pid "${FRONTEND_PID}" "Frontend"
  exit "${code}"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --env-file)
        shift
        [[ $# -gt 0 ]] || { echo "缺少 --env-file 参数值"; exit 1; }
        ENV_FILE="$1"
        ;;
      --web-host)
        shift
        [[ $# -gt 0 ]] || { echo "缺少 --web-host 参数值"; exit 1; }
        WEB_HOST="$1"
        ;;
      --web-port)
        shift
        [[ $# -gt 0 ]] || { echo "缺少 --web-port 参数值"; exit 1; }
        WEB_PORT="$1"
        ;;
      --frontend-host)
        shift
        [[ $# -gt 0 ]] || { echo "缺少 --frontend-host 参数值"; exit 1; }
        FRONTEND_HOST="$1"
        ;;
      --frontend-port)
        shift
        [[ $# -gt 0 ]] || { echo "缺少 --frontend-port 参数值"; exit 1; }
        FRONTEND_PORT="$1"
        ;;
      --web-only)
        START_WEB=1
        START_FRONTEND=0
        RUN_FRONTEND_BUILD=0
        ;;
      --frontend-only)
        START_WEB=0
        START_FRONTEND=1
        RUN_BACKEND_COMPILE=0
        ;;
      --skip-backend-compile)
        RUN_BACKEND_COMPILE=0
        ;;
      --skip-frontend-build)
        RUN_FRONTEND_BUILD=0
        ;;
      --with-preflight)
        RUN_PREFLIGHT=1
        ;;
      --install-python-deps)
        INSTALL_PY_DEPS=1
        ;;
      --install-frontend-deps)
        INSTALL_FE_DEPS=1
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "未知参数: $1"
        usage
        exit 1
        ;;
    esac
    shift
  done
}

monitor_processes() {
  while true; do
    if [[ -n "${WEB_PID}" ]] && ! kill -0 "${WEB_PID}" 2>/dev/null; then
      local status=0
      if ! wait "${WEB_PID}"; then
        status=$?
      fi
      log "Web 进程已退出，状态码=${status}"
      cleanup "${status}"
    fi

    if [[ -n "${FRONTEND_PID}" ]] && ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
      local status=0
      if ! wait "${FRONTEND_PID}"; then
        status=$?
      fi
      log "Frontend 进程已退出，状态码=${status}"
      cleanup "${status}"
    fi

    sleep 1
  done
}

main() {
  parse_args "$@"
  cd "${ROOT_DIR}"

  if [[ "${START_WEB}" == "0" && "${START_FRONTEND}" == "0" ]]; then
    echo "web 与 frontend 均未启用，无需执行。"
    exit 1
  fi

  require_cmd python3
  if [[ "${START_FRONTEND}" == "1" || "${RUN_FRONTEND_BUILD}" == "1" || "${INSTALL_FE_DEPS}" == "1" ]]; then
    require_cmd npm
  fi

  if [[ "${START_WEB}" == "1" ]] && [[ ! -f "${ENV_FILE}" ]]; then
    echo "未找到环境文件: ${ENV_FILE}"
    echo "请先复制并配置: cp .env.web.example ${ENV_FILE}"
    exit 1
  fi

  trap 'cleanup $?' EXIT
  trap 'cleanup 130' INT TERM

  log "本地编译并启动流程开始"

  if [[ "${INSTALL_PY_DEPS}" == "1" ]]; then
    log "1/6 安装 Python 依赖"
    python3 -m pip install -e .
  fi

  if [[ "${INSTALL_FE_DEPS}" == "1" ]]; then
    log "2/6 安装前端依赖"
    npm --prefix frontend install
  elif [[ "${RUN_FRONTEND_BUILD}" == "1" || "${START_FRONTEND}" == "1" ]] && [[ ! -d "frontend/node_modules" ]]; then
    log "2/6 检测到 frontend/node_modules 缺失，自动安装依赖"
    npm --prefix frontend install
  fi

  if [[ "${RUN_PREFLIGHT}" == "1" ]]; then
    log "3/6 执行发版预检"
    bash scripts/release-preflight.sh
  fi

  if [[ "${RUN_BACKEND_COMPILE}" == "1" ]]; then
    log "4/6 后端编译检查"
    python3 -m compileall src/foundation src/ops src/biz src/app src/shared src/scripts src/platform src/operations
  fi

  if [[ "${RUN_FRONTEND_BUILD}" == "1" ]]; then
    log "5/6 前端构建"
    npm --prefix frontend run build
  fi

  if [[ "${START_WEB}" == "1" ]]; then
    log "6/6 启动 Web: http://${WEB_HOST}:${WEB_PORT}"
    GOLDENSHARE_ENV_FILE="${ENV_FILE}" python3 -m src.app.web.run --host "${WEB_HOST}" --port "${WEB_PORT}" --no-reload &
    WEB_PID=$!
    sleep 2
    if ! kill -0 "${WEB_PID}" 2>/dev/null; then
      wait "${WEB_PID}" || true
      echo "Web 启动失败。"
      cleanup 1
    fi
  fi

  if [[ "${START_FRONTEND}" == "1" ]]; then
    log "启动 Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
    npm --prefix frontend run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" &
    FRONTEND_PID=$!
    sleep 2
    if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
      wait "${FRONTEND_PID}" || true
      echo "Frontend 启动失败。"
      cleanup 1
    fi
  fi

  echo ""
  echo "已启动服务："
  if [[ -n "${WEB_PID}" ]]; then
    echo "  - Web:      http://${WEB_HOST}:${WEB_PORT} (pid=${WEB_PID})"
    echo "  - API Docs: http://${WEB_HOST}:${WEB_PORT}/api/docs"
  fi
  if [[ -n "${FRONTEND_PID}" ]]; then
    echo "  - Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT} (pid=${FRONTEND_PID})"
  fi
  echo "按 Ctrl+C 可同时停止已启动进程。"

  monitor_processes
}

main "$@"
