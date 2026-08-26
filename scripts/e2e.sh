#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${ASTRA_E2E_BACKEND_PORT:-18100}"
FRONTEND_PORT="${ASTRA_E2E_FRONTEND_PORT:-15173}"
RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/astra-e2e.XXXXXX")"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"
BACKEND_PID=""
FRONTEND_PID=""

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -x "$ROOT_DIR/backend/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  [[ -z "$FRONTEND_PID" ]] || kill "$FRONTEND_PID" 2>/dev/null || true
  [[ -z "$BACKEND_PID" ]] || kill "$BACKEND_PID" 2>/dev/null || true
  [[ -z "$FRONTEND_PID" ]] || wait "$FRONTEND_PID" 2>/dev/null || true
  [[ -z "$BACKEND_PID" ]] || wait "$BACKEND_PID" 2>/dev/null || true
  if [[ $exit_code -ne 0 ]]; then
    echo ""
    echo "E2E 失败，后端日志："
    tail -n 80 "$BACKEND_LOG" 2>/dev/null || true
    echo ""
    echo "E2E 失败，前端日志："
    tail -n 80 "$FRONTEND_LOG" 2>/dev/null || true
  fi
  case "$RUN_DIR" in
    */astra-e2e.*) rm -rf -- "$RUN_DIR" ;;
  esac
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

wait_for_url() {
  local name="$1"
  local url="$2"
  for _ in $(seq 1 60); do
    if curl --silent --fail --max-time 2 "$url" >/dev/null; then
      echo "$name 已就绪：$url"
      return 0
    fi
    sleep 1
  done
  echo "$name 在 60 秒内未就绪：$url" >&2
  return 1
}

"$PYTHON_BIN" -c "import fastapi, sqlalchemy, uvicorn" >/dev/null
test -d "$ROOT_DIR/frontend/node_modules/@playwright/test" || {
  echo "缺少前端依赖，请先执行：cd frontend && npm ci" >&2
  exit 1
}

echo "启动隔离的 Astra E2E 环境..."
(
  cd "$ROOT_DIR/backend"
  PATH="$ROOT_DIR/scripts/fixtures:$PATH" \
  ASTRA_DATABASE_URL="sqlite+aiosqlite:///$RUN_DIR/astra-e2e.db" \
  ASTRA_WORKSPACE_ROOT="$RUN_DIR/workspaces" \
  ASTRA_SEED_DEMO="true" \
  "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
) >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
wait_for_url "后端" "http://127.0.0.1:$BACKEND_PORT/api/health"

(
  cd "$ROOT_DIR/frontend"
  VITE_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT" \
  npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT"
) >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
wait_for_url "前端" "http://127.0.0.1:$FRONTEND_PORT/"

echo "运行 Chromium 端到端验收..."
(
  cd "$ROOT_DIR/frontend"
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" npm run test:e2e
)

echo "E2E 验收通过。HTML 报告：artifacts/playwright-report/index.html"
echo "机器可读报告：artifacts/test-results/results.json"
