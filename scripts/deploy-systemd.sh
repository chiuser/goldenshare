#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${REPO_DIR:-/opt/goldenshare/goldenshare}"
BRANCH="${1:-main}"
ENV_FILE="${ENV_FILE:-/etc/goldenshare/web.env}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-/usr/bin/systemctl}"

WEB_SERVICE="${WEB_SERVICE:-goldenshare-web.service}"
WORKER_SERVICE="${WORKER_SERVICE:-goldenshare-ops-worker.service}"
SCHEDULER_SERVICE="${SCHEDULER_SERVICE:-goldenshare-ops-scheduler.service}"
RESTART_SCHEDULER="${RESTART_SCHEDULER:-1}"

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"

log() {
  echo "[$(date '+%F %T')] $*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "缺少命令: $1"
    exit 1
  }
}

require_file() {
  [[ -f "$1" ]] || {
    echo "缺少文件: $1"
    exit 1
  }
}

sudo_systemctl() {
  sudo -n "${SYSTEMCTL_BIN}" "$@"
}

ensure_sudo_ready() {
  if ! sudo_systemctl status "${WEB_SERVICE}" >/dev/null 2>&1; then
    cat <<'EOF'
当前用户无法无密码执行 sudo。
请先为部署用户配置受控 sudo 权限，至少允许：
  - systemctl daemon-reload
  - systemctl restart/status goldenshare-web.service
  - systemctl restart/status goldenshare-ops-worker.service
  - systemctl restart/status goldenshare-ops-scheduler.service
EOF
    exit 1
  fi
}

ensure_runtime_ready() {
  require_file "${ENV_FILE}"
  if [[ ! -r "${ENV_FILE}" ]]; then
    echo "环境文件不可读: ${ENV_FILE}"
    echo "请确保部署用户可读取该文件，或调整文件组权限。"
    exit 1
  fi
  require_file "${REPO_DIR}/.venv/bin/python"
  require_file "${REPO_DIR}/.venv/bin/pip"
  require_file "${REPO_DIR}/.venv/bin/goldenshare"
}

restart_services() {
  log "6/8 重新加载 systemd 配置"
  sudo_systemctl daemon-reload

  log "7/8 重启服务"
  sudo_systemctl restart "${WEB_SERVICE}"
  sudo_systemctl restart "${WORKER_SERVICE}"
  if [[ "${RESTART_SCHEDULER}" == "1" ]]; then
    sudo_systemctl restart "${SCHEDULER_SERVICE}"
  fi
}

health_check() {
  log "8/8 健康检查"
  local ok=0
  for i in {1..30}; do
    if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
      ok=1
      log "健康检查通过（第 ${i} 次）"
      break
    fi
    sleep 1
  done

  if [[ "${ok}" -ne 1 ]]; then
    echo "健康检查失败：30秒内 ${HEALTH_URL} 未就绪"
    echo "服务状态："
    sudo_systemctl status "${WEB_SERVICE}" || true
    sudo_systemctl status "${WORKER_SERVICE}" || true
    if [[ "${RESTART_SCHEDULER}" == "1" ]]; then
      sudo_systemctl status "${SCHEDULER_SERVICE}" || true
    fi
    exit 1
  fi
}

main() {
  log "开始发版，分支=${BRANCH}"
  require_cmd git
  require_cmd npm
  require_cmd curl
  require_cmd sudo
  require_cmd "${SYSTEMCTL_BIN}"

  ensure_sudo_ready
  ensure_runtime_ready

  cd "${REPO_DIR}"

  log "1/8 拉取代码"
  git fetch --all --prune
  git checkout "${BRANCH}"
  git pull --ff-only origin "${BRANCH}"

  log "2/8 校验运行环境"
  [[ -x .venv/bin/python ]] || { echo "缺少 .venv/bin/python"; exit 1; }
  [[ -x .venv/bin/pip ]] || { echo "缺少 .venv/bin/pip"; exit 1; }
  [[ -x .venv/bin/goldenshare ]] || { echo "缺少 .venv/bin/goldenshare"; exit 1; }

  log "3/8 安装后端依赖"
  .venv/bin/pip install -e ".[dev]"

  log "4/8 构建前端"
  cd "${REPO_DIR}/frontend"
  npm ci
  npm run build
  cd "${REPO_DIR}"

  log "5/8 执行数据库迁移"
  set -a
  source "${ENV_FILE}"
  set +a
  .venv/bin/goldenshare init-db

  restart_services
  health_check

  log "服务状态"
  sudo_systemctl status "${WEB_SERVICE}" || true
  sudo_systemctl status "${WORKER_SERVICE}" || true
  if [[ "${RESTART_SCHEDULER}" == "1" ]]; then
    sudo_systemctl status "${SCHEDULER_SERVICE}" || true
  fi

  log "发版完成"
}

main "$@"
