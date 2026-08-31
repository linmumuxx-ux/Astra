#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${ASTRA_E2E_BACKEND_PORT:-18100}"
FRONTEND_PORT="${ASTRA_E2E_FRONTEND_PORT:-15173}"
RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/astra-e2e.XXXXXX")"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"
REDIS_LOG="$RUN_DIR/redis.log"
RUNTIME_LOG="$RUN_DIR/runtime.log"
BACKEND_PID=""
FRONTEND_PID=""
REDIS_PID=""
RUNTIME_PID=""

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -x "$ROOT_DIR/backend/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi
REDIS_PORT="${ASTRA_E2E_REDIS_PORT:-$($PYTHON_BIN -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')}"
REDIS_URL="redis://127.0.0.1:$REDIS_PORT/0"
REDIS_SERVER_BIN="${ASTRA_REDIS_SERVER_BINARY:-$(command -v redis-server 2>/dev/null || true)}"
REDIS_CLI_BIN="${ASTRA_REDIS_CLI_BINARY:-$(command -v redis-cli 2>/dev/null || true)}"
if [[ -z "$REDIS_SERVER_BIN" && -x /opt/homebrew/opt/redis/bin/redis-server ]]; then
  REDIS_SERVER_BIN=/opt/homebrew/opt/redis/bin/redis-server
fi
if [[ -z "$REDIS_CLI_BIN" && -x /opt/homebrew/opt/redis/bin/redis-cli ]]; then
  REDIS_CLI_BIN=/opt/homebrew/opt/redis/bin/redis-cli
fi

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  [[ -z "$FRONTEND_PID" ]] || kill "$FRONTEND_PID" 2>/dev/null || true
  [[ -z "$RUNTIME_PID" ]] || kill "$RUNTIME_PID" 2>/dev/null || true
  [[ -z "$BACKEND_PID" ]] || kill "$BACKEND_PID" 2>/dev/null || true
  [[ -z "$REDIS_PID" ]] || kill "$REDIS_PID" 2>/dev/null || true
  [[ -z "$FRONTEND_PID" ]] || wait "$FRONTEND_PID" 2>/dev/null || true
  [[ -z "$RUNTIME_PID" ]] || wait "$RUNTIME_PID" 2>/dev/null || true
  [[ -z "$BACKEND_PID" ]] || wait "$BACKEND_PID" 2>/dev/null || true
  [[ -z "$REDIS_PID" ]] || wait "$REDIS_PID" 2>/dev/null || true
  if [[ $exit_code -ne 0 ]]; then
    echo ""
    echo "E2E 失败，后端日志："
    tail -n 80 "$BACKEND_LOG" 2>/dev/null || true
    echo ""
    echo "E2E 失败，前端日志："
    tail -n 80 "$FRONTEND_LOG" 2>/dev/null || true
    echo ""
    echo "E2E 失败，运行时日志："
    tail -n 120 "$RUNTIME_LOG" 2>/dev/null || true
    echo ""
    echo "E2E 失败，Redis 日志："
    tail -n 40 "$REDIS_LOG" 2>/dev/null || true
  fi
  case "$RUN_DIR" in
    */astra-e2e.*) rm -rf -- "$RUN_DIR" ;;
  esac
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

runtime_environment() {
  export PATH="$ROOT_DIR/scripts/fixtures:$PATH"
  export ASTRA_DATABASE_URL="sqlite+aiosqlite:///$RUN_DIR/astra-e2e.db"
  export ASTRA_WORKSPACE_ROOT="$RUN_DIR/workspaces"
  export ASTRA_SEED_DEMO="true"
  export ASTRA_REDIS_URL="$REDIS_URL"
  # 系统 E2E 的可重复 fixture 只验证显式隔离的 CLI fallback。
  export ASTRA_EXECUTOR_TYPE="opencode_cli_fallback"
  export ASTRA_SCOUT_INTERVAL="3600"
  export ASTRA_DISPATCHER_INTERVAL="1"
  export ASTRA_HEARTBEAT_INTERVAL="1"
  export ASTRA_HEARTBEAT_TIMEOUT="30"
  export ASTRA_RECOVERY_INTERVAL="3600"
}

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

wait_for_runtime() {
  for _ in $(seq 1 60); do
    if ! kill -0 "$RUNTIME_PID" 2>/dev/null; then
      echo "任务运行时意外退出" >&2
      return 1
    fi
    if grep -q "ready\." "$RUNTIME_LOG" 2>/dev/null; then
      echo "任务运行时已就绪"
      return 0
    fi
    sleep 1
  done
  echo "任务运行时在 60 秒内未就绪" >&2
  return 1
}

"$PYTHON_BIN" -c "import fastapi, sqlalchemy, uvicorn" >/dev/null
[[ -n "$REDIS_SERVER_BIN" && -x "$REDIS_SERVER_BIN" && -n "$REDIS_CLI_BIN" && -x "$REDIS_CLI_BIN" ]] || {
  echo "缺少 Redis，请先安装 redis-server。" >&2
  exit 1
}
test -d "$ROOT_DIR/frontend/node_modules/@playwright/test" || {
  echo "缺少前端依赖，请先执行：cd frontend && npm ci" >&2
  exit 1
}

echo "启动隔离的 Astra E2E 环境..."
"$REDIS_SERVER_BIN" --bind 127.0.0.1 --port "$REDIS_PORT" --save '' --appendonly no --dir "$RUN_DIR" >"$REDIS_LOG" 2>&1 &
REDIS_PID=$!
for _ in $(seq 1 30); do
  "$REDIS_CLI_BIN" -h 127.0.0.1 -p "$REDIS_PORT" ping 2>/dev/null | grep -q PONG && break
  sleep 1
done
"$REDIS_CLI_BIN" -h 127.0.0.1 -p "$REDIS_PORT" ping 2>/dev/null | grep -q PONG || {
  echo "Redis 在 30 秒内未就绪" >&2
  exit 1
}
echo "Redis 已就绪：127.0.0.1:$REDIS_PORT"

(
  cd "$ROOT_DIR/backend"
  runtime_environment
  "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
) >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
wait_for_url "后端" "http://127.0.0.1:$BACKEND_PORT/api/health"

(
  cd "$ROOT_DIR/backend"
  runtime_environment
  "$PYTHON_BIN" -m celery -A app.runtime.celery_app:celery worker --beat --loglevel=INFO --pool=solo --hostname="astra-e2e@%h" --schedule "$RUN_DIR/celerybeat-schedule"
) >"$RUNTIME_LOG" 2>&1 &
RUNTIME_PID=$!
wait_for_runtime

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
