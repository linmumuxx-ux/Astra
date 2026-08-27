#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
CELERY_BIN="$ROOT_DIR/.venv/bin/celery"
REDIS_URL="${ASTRA_REDIS_URL:-redis://localhost:6379/0}"
RUNTIME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/astra-runtime.XXXXXX")"
REDIS_PID=""

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ -n "$REDIS_PID" ]]; then
    kill "$REDIS_PID" 2>/dev/null || true
    wait "$REDIS_PID" 2>/dev/null || true
  fi
  rm -rf "$RUNTIME_DIR"
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

if [[ ! -x "$PYTHON_BIN" || ! -x "$CELERY_BIN" ]]; then
  echo "Astra Python 环境未安装。请先在仓库根目录创建 .venv 并安装 backend 依赖。" >&2
  exit 1
fi

redis_ready() {
  ASTRA_RUNTIME_REDIS_URL="$REDIS_URL" "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import os

from redis import Redis

client = Redis.from_url(os.environ["ASTRA_RUNTIME_REDIS_URL"], socket_connect_timeout=1)
client.ping()
PY
}

if ! redis_ready; then
  if [[ "$REDIS_URL" != "redis://localhost:6379/0" && "$REDIS_URL" != "redis://127.0.0.1:6379/0" ]]; then
    echo "无法连接 ASTRA_REDIS_URL 指定的 Redis，请先启动并检查该服务。" >&2
    exit 1
  fi

  REDIS_BIN="${ASTRA_REDIS_BINARY:-}"
  if [[ -z "$REDIS_BIN" ]] && command -v redis-server >/dev/null 2>&1; then
    REDIS_BIN="$(command -v redis-server)"
  fi
  if [[ -z "$REDIS_BIN" && -x /opt/homebrew/opt/redis/bin/redis-server ]]; then
    REDIS_BIN="/opt/homebrew/opt/redis/bin/redis-server"
  fi
  if [[ -z "$REDIS_BIN" ]]; then
    echo "Redis 未运行且找不到 redis-server。请安装 Redis 或设置 ASTRA_REDIS_URL。" >&2
    exit 1
  fi

  echo "启动本地临时 Redis（127.0.0.1:6379）..."
  "$REDIS_BIN" --save '' --appendonly no --dir "$RUNTIME_DIR" --bind 127.0.0.1 --port 6379 >"$RUNTIME_DIR/redis.log" 2>&1 &
  REDIS_PID=$!
  for _ in {1..30}; do
    if redis_ready; then
      break
    fi
    sleep 0.1
  done
  if ! redis_ready; then
    echo "Redis 启动失败，日志：$RUNTIME_DIR/redis.log" >&2
    exit 1
  fi
fi

echo "Astra 调度运行时已启动。按 Ctrl+C 停止。"
echo "Redis: 已连接"
cd "$BACKEND_DIR"
"$CELERY_BIN" -A app.runtime.celery_app:celery worker \
  --beat \
  --loglevel=INFO \
  --pool=solo \
  --hostname='astra-local@%h' \
  --schedule "$RUNTIME_DIR/celerybeat-schedule"
