#!/usr/bin/env bash
set -Eeuo pipefail

# 统一一键发版入口（兼容旧命令）：
#   bash scripts/deploy-systemd.sh main
# 内部转发到最新分层发布脚本。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAYERED_SCRIPT="${SCRIPT_DIR}/deploy-layered-systemd.sh"
BRANCH="${1:-main}"

# 兼容旧变量：RESTART_SCHEDULER=0 等价于 DEPLOY_OPS=0
if [[ -n "${RESTART_SCHEDULER:-}" && "${RESTART_SCHEDULER}" == "0" && -z "${DEPLOY_OPS:-}" ]]; then
  export DEPLOY_OPS=0
fi

# 默认保持“全量发布”行为
export DEPLOY_FOUNDATION="${DEPLOY_FOUNDATION:-1}"
export DEPLOY_OPS="${DEPLOY_OPS:-1}"
export DEPLOY_PLATFORM="${DEPLOY_PLATFORM:-1}"
export RUN_DB_MIGRATION="${RUN_DB_MIGRATION:-1}"
export RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-1}"

if [[ ! -x "${LAYERED_SCRIPT}" ]]; then
  echo "缺少可执行脚本: ${LAYERED_SCRIPT}"
  echo "请执行: chmod +x scripts/deploy-layered-systemd.sh"
  exit 1
fi

exec "${LAYERED_SCRIPT}" "${BRANCH}"
