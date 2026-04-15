#!/usr/bin/env bash
set -Eeuo pipefail

# 统一一键发版入口（兼容旧命令）：
#   bash scripts/deploy-systemd.sh main
# 内部转发到最新分层发布脚本。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAYERED_SCRIPT="${SCRIPT_DIR}/deploy-layered-systemd.sh"
BRANCH="main"

usage() {
  cat <<'EOF'
用法:
  bash scripts/deploy-systemd.sh [branch] [options]

选项:
  --branch <name>         指定分支（等价于位置参数）
  --platform-only         仅发布 platform(web)
  --ops-only              仅发布 ops(scheduler)
  --foundation-only       仅发布 foundation(worker)
  --seed-default-source   启用“默认单源规则缺失检测 + 按需初始化”（默认启用）
  --skip-seed-default-source 关闭“默认单源规则缺失检测 + 按需初始化”
  --seed-source <key>     初始化使用的数据源（默认 tushare）
  --seed-pipeline-mode    启用“pipeline_mode 缺失/漂移检测 + 按需初始化”（默认启用）
  --skip-seed-pipeline-mode 关闭“pipeline_mode 缺失/漂移检测 + 按需初始化”
  --skip-build            跳过前端构建
  --skip-migration        跳过数据库迁移
  --full                  全量发布（默认）
  -h, --help              显示帮助

示例:
  bash scripts/deploy-systemd.sh dev-interface --platform-only
  bash scripts/deploy-systemd.sh --branch dev-interface --skip-build
  bash scripts/deploy-systemd.sh dev-interface --seed-default-source --seed-source tushare
EOF
}

# 默认保持“全量发布”行为
export DEPLOY_FOUNDATION="${DEPLOY_FOUNDATION:-1}"
export DEPLOY_OPS="${DEPLOY_OPS:-1}"
export DEPLOY_PLATFORM="${DEPLOY_PLATFORM:-1}"
export RUN_DB_MIGRATION="${RUN_DB_MIGRATION:-1}"
export RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-1}"
export RUN_DEFAULT_SINGLE_SOURCE_SEED="${RUN_DEFAULT_SINGLE_SOURCE_SEED:-1}"
export DEFAULT_SINGLE_SOURCE_SEED_KEY="${DEFAULT_SINGLE_SOURCE_SEED_KEY:-tushare}"
export RUN_DATASET_PIPELINE_MODE_SEED="${RUN_DATASET_PIPELINE_MODE_SEED:-1}"

if [[ $# -gt 0 && "${1}" != -* ]]; then
  BRANCH="$1"
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)
      shift
      [[ $# -gt 0 ]] || { echo "缺少 --branch 参数值"; exit 1; }
      BRANCH="$1"
      ;;
    --platform-only)
      export DEPLOY_FOUNDATION=0
      export DEPLOY_OPS=0
      export DEPLOY_PLATFORM=1
      ;;
    --ops-only)
      export DEPLOY_FOUNDATION=0
      export DEPLOY_OPS=1
      export DEPLOY_PLATFORM=0
      ;;
    --foundation-only)
      export DEPLOY_FOUNDATION=1
      export DEPLOY_OPS=0
      export DEPLOY_PLATFORM=0
      ;;
    --skip-build)
      export RUN_FRONTEND_BUILD=0
      ;;
    --seed-default-source)
      export RUN_DEFAULT_SINGLE_SOURCE_SEED=1
      ;;
    --skip-seed-default-source)
      export RUN_DEFAULT_SINGLE_SOURCE_SEED=0
      ;;
    --seed-source)
      shift
      [[ $# -gt 0 ]] || { echo "缺少 --seed-source 参数值"; exit 1; }
      export DEFAULT_SINGLE_SOURCE_SEED_KEY="$1"
      ;;
    --seed-pipeline-mode)
      export RUN_DATASET_PIPELINE_MODE_SEED=1
      ;;
    --skip-seed-pipeline-mode)
      export RUN_DATASET_PIPELINE_MODE_SEED=0
      ;;
    --skip-migration)
      export RUN_DB_MIGRATION=0
      ;;
    --full)
      export DEPLOY_FOUNDATION=1
      export DEPLOY_OPS=1
      export DEPLOY_PLATFORM=1
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

# 兼容旧变量：RESTART_SCHEDULER=0 等价于 DEPLOY_OPS=0
if [[ -n "${RESTART_SCHEDULER:-}" && "${RESTART_SCHEDULER}" == "0" && -z "${DEPLOY_OPS+x}" ]]; then
  export DEPLOY_OPS=0
fi

if [[ ! -x "${LAYERED_SCRIPT}" ]]; then
  echo "缺少可执行脚本: ${LAYERED_SCRIPT}"
  echo "请执行: chmod +x scripts/deploy-layered-systemd.sh"
  exit 1
fi

exec "${LAYERED_SCRIPT}" "${BRANCH}"
