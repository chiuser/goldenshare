#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${LAKE_CONSOLE_PORT:-8010}"
FRONTEND_PORT="${LAKE_CONSOLE_FRONTEND_PORT:-5178}"
PYTHON_BIN="${LAKE_CONSOLE_PYTHON:-${ROOT_DIR}/lake_console/.venv/bin/python}"

cd "${ROOT_DIR}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "缺少 Lake Console Python 运行环境：${PYTHON_BIN}" >&2
  echo "请先创建并安装依赖：python3 -m venv lake_console/.venv && lake_console/.venv/bin/pip install -r lake_console/backend/requirements.txt" >&2
  exit 1
fi

LAKE_ROOT="$("${PYTHON_BIN}" - <<'PY'
from lake_console.backend.app.settings import load_settings

settings = load_settings()
print(settings.lake_root)
PY
)"

echo "[lake-console] root=${LAKE_ROOT}"
echo "[lake-console] python=${PYTHON_BIN}"
echo "[lake-console] backend=http://127.0.0.1:${BACKEND_PORT}"
echo "[lake-console] frontend=http://127.0.0.1:${FRONTEND_PORT}"
echo "[lake-console] 启动后按 Ctrl+C 退出"

"${PYTHON_BIN}" -m lake_console.backend.app.main &
BACKEND_PID=$!

cleanup() {
  kill "${BACKEND_PID}" 2>/dev/null || true
}
trap cleanup EXIT

cd "${ROOT_DIR}/lake_console/frontend"
npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}"
