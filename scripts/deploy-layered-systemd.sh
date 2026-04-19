#!/usr/bin/env bash
set -Eeuo pipefail
export SYSTEMD_PAGER=""
export SYSTEMD_LESS=""
export PAGER=cat

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
RUN_MONEYFLOW_MULTI_SOURCE_SEED="${RUN_MONEYFLOW_MULTI_SOURCE_SEED:-1}"
RUN_SYNC_UNITS="${RUN_SYNC_UNITS:-1}"
PIP_INSTALL_TARGET="${PIP_INSTALL_TARGET:-.}"
DEPLOY_LOCK_FILE="${DEPLOY_LOCK_FILE:-/tmp/goldenshare-deploy.lock}"
DEPLOY_LOCK_WAIT_SECONDS="${DEPLOY_LOCK_WAIT_SECONDS:-30}"
SYSTEMD_UNIT_DIR="${SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
WEB_UNIT_SRC="${WEB_UNIT_SRC:-${SCRIPT_DIR}/goldenshare-web.service}"
WORKER_UNIT_SRC="${WORKER_UNIT_SRC:-${SCRIPT_DIR}/goldenshare-ops-worker.service}"
SCHEDULER_UNIT_SRC="${SCHEDULER_UNIT_SRC:-${SCRIPT_DIR}/goldenshare-ops-scheduler.service}"

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
HEALTH_V1_URL="${HEALTH_V1_URL:-http://127.0.0.1:8000/api/v1/health}"
EXPECTED_WEB_ENTRY_MODULE="${EXPECTED_WEB_ENTRY_MODULE:-src.app.web.run}"

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

sync_systemd_unit() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "${src}" ]]; then
    echo "缺少 unit 源文件: ${src}"
    exit 1
  fi
  if [[ -f "${dst}" ]] && cmp -s "${src}" "${dst}"; then
    return 1
  fi
  if ! sudo -n install -m 644 "${src}" "${dst}" >/dev/null 2>&1; then
    echo "同步 unit 失败: ${dst}"
    echo "请确认部署用户具备 sudo 安装 unit 权限，或使用 --skip-sync-units 跳过。"
    exit 1
  fi
  log "已同步 unit: ${dst}"
  return 0
}

sync_units_if_needed() {
  if [[ "${RUN_SYNC_UNITS}" != "1" ]]; then
    log "4/13 跳过 unit 同步（RUN_SYNC_UNITS=0）"
    return
  fi
  local changed=0
  local web_dst="${SYSTEMD_UNIT_DIR}/${WEB_SERVICE}"
  local worker_dst="${SYSTEMD_UNIT_DIR}/${WORKER_SERVICE}"
  local scheduler_dst="${SYSTEMD_UNIT_DIR}/${SCHEDULER_SERVICE}"

  if sync_systemd_unit "${WEB_UNIT_SRC}" "${web_dst}"; then
    changed=1
  fi
  if sync_systemd_unit "${WORKER_UNIT_SRC}" "${worker_dst}"; then
    changed=1
  fi
  if sync_systemd_unit "${SCHEDULER_UNIT_SRC}" "${scheduler_dst}"; then
    changed=1
  fi

  if [[ "${changed}" == "1" ]]; then
    log "检测到 unit 变更，执行 systemd daemon-reload"
    sudo_systemctl daemon-reload
  else
    log "unit 无变化，跳过同步写入"
  fi
}

assert_web_entry_module() {
  local output
  output="$(sudo_systemctl cat "${WEB_SERVICE}" 2>/dev/null || true)"
  if [[ -z "${output}" ]]; then
    echo "无法读取 ${WEB_SERVICE} 配置，请检查 systemd 状态。"
    exit 1
  fi
  if ! printf '%s\n' "${output}" | grep -q "${EXPECTED_WEB_ENTRY_MODULE}"; then
    echo "当前 ${WEB_SERVICE} 未指向期望入口模块: ${EXPECTED_WEB_ENTRY_MODULE}"
    echo "请同步 unit 后重试。"
    exit 1
  fi
}

acquire_deploy_lock() {
  require_cmd flock
  mkdir -p "$(dirname "${DEPLOY_LOCK_FILE}")"
  exec 9>"${DEPLOY_LOCK_FILE}"
  if ! flock -w "${DEPLOY_LOCK_WAIT_SECONDS}" 9; then
    echo "获取部署锁超时（${DEPLOY_LOCK_FILE}），请稍后重试。"
    exit 1
  fi
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

print_service_status() {
  local service_name="$1"
  local output
  if output="$(sudo_systemctl status "${service_name}" 2>&1)"; then
    printf '%s\n' "${output}" | cat
    return 0
  fi
  if printf '%s' "${output}" | grep -qiE "password is required|not allowed to run sudo|a terminal is required"; then
    log "跳过状态打印（sudo 规则未覆盖: systemctl status ${service_name}）"
    return 0
  fi
  printf '%s\n' "${output}" | cat
  return 0
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
  require_cmd cmp
  require_cmd install
  require_cmd "${SYSTEMCTL_BIN}"

  acquire_deploy_lock
  ensure_sudo_ready
  ensure_runtime_ready

  cd "${REPO_DIR}"

  log "1/12 拉取代码"
  git fetch --all --prune
  git checkout "${BRANCH}"
  git pull --ff-only origin "${BRANCH}"

  log "2/12 安装后端依赖（target=${PIP_INSTALL_TARGET}）"
  .venv/bin/pip install -e "${PIP_INSTALL_TARGET}"

  if [[ "${RUN_FRONTEND_BUILD}" == "1" ]]; then
    log "3/12 构建前端"
    cd "${REPO_DIR}/frontend"
    npm ci
    npm run build
    cd "${REPO_DIR}"
  else
    log "3/12 跳过前端构建（RUN_FRONTEND_BUILD=0）"
  fi

  sync_units_if_needed
  assert_web_entry_module

  if [[ "${RUN_DB_MIGRATION}" == "1" ]]; then
    log "5/12 执行数据库迁移"
    set -a
    source "${ENV_FILE}"
    set +a
    .venv/bin/goldenshare init-db
  else
    log "5/12 跳过数据库迁移（RUN_DB_MIGRATION=0）"
  fi

  if [[ "${RUN_DEFAULT_SINGLE_SOURCE_SEED}" == "1" ]]; then
    log "6/12 检测默认单源规则缺失（source=${DEFAULT_SINGLE_SOURCE_SEED_KEY}）"
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
    log "6/12 跳过默认单源规则检测/初始化（RUN_DEFAULT_SINGLE_SOURCE_SEED=0）"
  fi

  if [[ "${RUN_DATASET_PIPELINE_MODE_SEED}" == "1" ]]; then
    log "7/12 检测数据集 pipeline_mode 缺失/漂移"
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
    log "7/12 跳过 pipeline_mode 检测/初始化（RUN_DATASET_PIPELINE_MODE_SEED=0）"
  fi

  if [[ "${RUN_MONEYFLOW_MULTI_SOURCE_SEED}" == "1" ]]; then
    log "8/12 检测 moneyflow 多源融合骨架"
    set -a
    source "${ENV_FILE}"
    set +a
    moneyflow_preview="$(
      .venv/bin/goldenshare ops-seed-moneyflow-multi-source
    )"
    echo "${moneyflow_preview}"
    moneyflow_delta="$(
      printf '%s\n' "${moneyflow_preview}" \
        | awk -F= '/^(created_pipeline_mode|updated_pipeline_mode|created_mapping_rules|created_cleansing_rules|created_source_statuses|created_resolution_policy|updated_resolution_policy)=/{sum+=$2} END{print sum+0}'
    )"
    if [[ "${moneyflow_delta}" -gt 0 ]]; then
      log "检测到 moneyflow 多源骨架需写入 ${moneyflow_delta} 项，执行按需初始化"
      .venv/bin/goldenshare ops-seed-moneyflow-multi-source --apply
    else
      log "未检测到 moneyflow 多源骨架变更，跳过初始化写入"
    fi
  else
    log "8/12 跳过 moneyflow 多源骨架检测/初始化（RUN_MONEYFLOW_MULTI_SOURCE_SEED=0）"
  fi

  log "9/12 重新加载 systemd 配置"
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

  log "10/12 Foundation 自检"
  .venv/bin/goldenshare list-resources >/dev/null

  log "11/12 Ops 自检"
  .venv/bin/goldenshare ops-reconcile-executions --stale-for-minutes 30 >/dev/null

  log "12/12 Platform 健康检查"
  health_check "${HEALTH_URL}" "Platform /api/health"
  health_check "${HEALTH_V1_URL}" "Platform /api/v1/health"

  log "13/13 服务状态"
  print_service_status "${WEB_SERVICE}"
  print_service_status "${WORKER_SERVICE}"
  print_service_status "${SCHEDULER_SERVICE}"

  log "分层发版完成"
}

main "$@"
