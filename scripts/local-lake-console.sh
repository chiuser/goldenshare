#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${LAKE_CONSOLE_PORT:-8010}"
FRONTEND_PORT="${LAKE_CONSOLE_FRONTEND_PORT:-5178}"

cd "${ROOT_DIR}"

LAKE_ROOT="$(python3 - <<'PY'
from lake_console.backend.app.settings import load_settings

settings = load_settings()
print(settings.lake_root)
PY
)"

echo "[lake-console] root=${LAKE_ROOT}"
echo "[lake-console] backend=http://127.0.0.1:${BACKEND_PORT}"
echo "[lake-console] frontend=http://127.0.0.1:${FRONTEND_PORT}"
echo "[lake-console] 启动后按 Ctrl+C 退出"

python3 -m lake_console.backend.app.main &
BACKEND_PID=$!

cleanup() {
  kill "${BACKEND_PID}" 2>/dev/null || true
}
trap cleanup EXIT

cd "${ROOT_DIR}/lake_console/frontend"
npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}"
