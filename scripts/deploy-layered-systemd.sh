#!/usr/bin/env bash
set -Eeuo pipefail
export SYSTEMD_PAGER=""
export SYSTEMD_LESS=""
export PAGER=cat

REPO_DIR="${REPO_DIR:-/opt/goldenshare/goldenshare}"
BRANCH="${1:-main}"
ENV_FILE="${ENV_FILE:-/etc/goldenshare/web.env}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-/usr/bin/systemctl}"

WEB_SERVICE="${WEB_SERVICE:-goldenshare-web.service}"
WORKER_SERVICE="${WORKER_SERVICE:-goldenshare-ops-worker.service}"
SCHEDULER_SERVICE="${SCHEDULER_SERVICE:-goldenshare-ops-scheduler.service}"

DEPLOY_FOUNDATION="${DEPLOY_FOUNDATION:-1}"
DEPLOY_OPS="${DEPLOY_OPS:-1}"
DEPLOY_PLATFORM="${DEPLOY_PLATFORM:-1}"
RUN_DB_MIGRATION="${RUN_DB_MIGRATION:-1}"
RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-1}"
RUN_DEFAULT_SINGLE_SOURCE_SEED="${RUN_DEFAULT_SINGLE_SOURCE_SEED:-1}"
DEFAULT_SINGLE_SOURCE_SEED_KEY="${DEFAULT_SINGLE_SOURCE_SEED_KEY:-tushare}"
RUN_DATASET_PIPELINE_MODE_SEED="${RUN_DATASET_PIPELINE_MODE_SEED:-1}"

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
HEALTH_V1_URL="${HEALTH_V1_URL:-http://127.0.0.1:8000/api/v1/health}"

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
  if ! sudo_systemctl daemon-reload >/dev/null 2>&1; then
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
  require_file "${REPO_DIR}/.venv/bin/python"
  require_file "${REPO_DIR}/.venv/bin/pip"
  require_file "${REPO_DIR}/.venv/bin/goldenshare"
}

restart_layer_services() {
  local layer="$1"
  case "${layer}" in
    foundation)
      log "重启 Foundation 执行层（worker）"
      sudo_systemctl restart "${WORKER_SERVICE}"
      ;;
    ops)
      log "重启 Ops 调度层（scheduler）"
      sudo_systemctl restart "${SCHEDULER_SERVICE}"
      ;;
    platform)
      log "重启 Platform 接口层（web）"
      sudo_systemctl restart "${WEB_SERVICE}"
      ;;
    *)
      echo "未知层: ${layer}"
      exit 1
      ;;
  esac
}

health_check() {
  local url="$1"
  local label="$2"
  local ok=0
  for i in {1..30}; do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      ok=1
      log "${label} 健康检查通过（第 ${i} 次）"
      break
    fi
    sleep 1
  done
  if [[ "${ok}" -ne 1 ]]; then
    echo "${label} 健康检查失败：30秒内 ${url} 未就绪"
    exit 1
  fi
}

main() {
  log "开始分层发版，分支=${BRANCH}"
  require_cmd git
  require_cmd npm
  require_cmd curl
  require_cmd sudo
  require_cmd "${SYSTEMCTL_BIN}"

  ensure_sudo_ready
  ensure_runtime_ready

  cd "${REPO_DIR}"

  log "1/11 拉取代码"
  git fetch --all --prune
  git checkout "${BRANCH}"
  git pull --ff-only origin "${BRANCH}"

  log "2/11 安装后端依赖"
  .venv/bin/pip install -e ".[dev]"

  if [[ "${RUN_FRONTEND_BUILD}" == "1" ]]; then
    log "3/11 构建前端"
    cd "${REPO_DIR}/frontend"
    npm ci
    npm run build
    cd "${REPO_DIR}"
  else
    log "3/11 跳过前端构建（RUN_FRONTEND_BUILD=0）"
  fi

  if [[ "${RUN_DB_MIGRATION}" == "1" ]]; then
    log "4/11 执行数据库迁移"
    set -a
    source "${ENV_FILE}"
    set +a
    .venv/bin/goldenshare init-db
  else
    log "4/11 跳过数据库迁移（RUN_DB_MIGRATION=0）"
  fi

  if [[ "${RUN_DEFAULT_SINGLE_SOURCE_SEED}" == "1" ]]; then
    log "5/11 检测默认单源规则缺失（source=${DEFAULT_SINGLE_SOURCE_SEED_KEY}）"
    set -a
    source "${ENV_FILE}"
    set +a
    seed_preview="$(
      .venv/bin/goldenshare ops-seed-default-single-source --source-key "${DEFAULT_SINGLE_SOURCE_SEED_KEY}"
    )"
    echo "${seed_preview}"
    missing_total="$(
      printf '%s\n' "${seed_preview}" \
        | awk -F= '/^created_(mapping_rules|cleansing_rules|resolution_policies|source_statuses)=/{sum+=$2} END{print sum+0}'
    )"
    if [[ "${missing_total}" -gt 0 ]]; then
      log "检测到缺失规则 ${missing_total} 项，执行按需初始化"
      .venv/bin/goldenshare ops-seed-default-single-source --apply --source-key "${DEFAULT_SINGLE_SOURCE_SEED_KEY}"
    else
      log "未检测到缺失规则，跳过初始化写入"
    fi
  else
    log "5/11 跳过默认单源规则检测/初始化（RUN_DEFAULT_SINGLE_SOURCE_SEED=0）"
  fi

  if [[ "${RUN_DATASET_PIPELINE_MODE_SEED}" == "1" ]]; then
    log "6/11 检测数据集 pipeline_mode 缺失/漂移"
    set -a
    source "${ENV_FILE}"
    set +a
    pipeline_mode_preview="$(
      .venv/bin/goldenshare ops-seed-dataset-pipeline-mode
    )"
    echo "${pipeline_mode_preview}"
    pipeline_mode_delta="$(
      printf '%s\n' "${pipeline_mode_preview}" \
        | awk -F= '/^(created|updated)=/{sum+=$2} END{print sum+0}'
    )"
    if [[ "${pipeline_mode_delta}" -gt 0 ]]; then
      log "检测到 pipeline_mode 需写入 ${pipeline_mode_delta} 项，执行按需初始化"
      .venv/bin/goldenshare ops-seed-dataset-pipeline-mode --apply
    else
      log "未检测到 pipeline_mode 变更，跳过初始化写入"
    fi
  else
    log "6/11 跳过 pipeline_mode 检测/初始化（RUN_DATASET_PIPELINE_MODE_SEED=0）"
  fi

  log "7/11 重新加载 systemd 配置"
  sudo_systemctl daemon-reload

  if [[ "${DEPLOY_FOUNDATION}" == "1" ]]; then
    restart_layer_services foundation
  else
    log "跳过 Foundation 层重启（DEPLOY_FOUNDATION=0）"
  fi

  if [[ "${DEPLOY_OPS}" == "1" ]]; then
    restart_layer_services ops
  else
    log "跳过 Ops 层重启（DEPLOY_OPS=0）"
  fi

  if [[ "${DEPLOY_PLATFORM}" == "1" ]]; then
    restart_layer_services platform
  else
    log "跳过 Platform 层重启（DEPLOY_PLATFORM=0）"
  fi

  log "8/11 Foundation 自检"
  .venv/bin/goldenshare list-resources >/dev/null

  log "9/11 Ops 自检"
  .venv/bin/goldenshare ops-reconcile-executions --stale-for-minutes 30 >/dev/null

  log "10/11 Platform 健康检查"
  health_check "${HEALTH_URL}" "Platform /api/health"
  health_check "${HEALTH_V1_URL}" "Platform /api/v1/health"

  log "11/11 服务状态"
  sudo_systemctl status "${WEB_SERVICE}" || true
  sudo_systemctl status "${WORKER_SERVICE}" || true
  sudo_systemctl status "${SCHEDULER_SERVICE}" || true

  log "分层发版完成"
}

main "$@"
