#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -x "$ROOT_DIR/backend/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

echo "[1/5] 后端静态检查"
(cd "$ROOT_DIR/backend" && "$PYTHON_BIN" -m ruff check app tests)

echo "[2/5] 后端测试"
(cd "$ROOT_DIR/backend" && "$PYTHON_BIN" -m pytest)

echo "[3/5] 前端类型检查"
(cd "$ROOT_DIR/frontend" && npm run type-check)

echo "[4/5] 前端生产构建"
(cd "$ROOT_DIR/frontend" && npm run build)

echo "[5/5] 浏览器 E2E"
"$ROOT_DIR/scripts/e2e.sh"

echo "Astra 全量验证通过。"
