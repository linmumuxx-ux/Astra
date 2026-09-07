#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
CELERY_BIN="$ROOT_DIR/.venv/bin/celery"
REDIS_URL="${ASTRA_REDIS_URL:-redis://localhost:6379/0}"
RUNTIME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/astra-runtime.XXXXXX")"
REDIS_PID=""
OPENCODE_PID=""
ASSISTANT_PID=""
BEAT_PID=""
CONTROL_PID=""

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ -n "$CONTROL_PID" ]]; then
    kill "$CONTROL_PID" 2>/dev/null || true
    wait "$CONTROL_PID" 2>/dev/null || true
  fi
  if [[ -n "$BEAT_PID" ]]; then
    kill "$BEAT_PID" 2>/dev/null || true
    wait "$BEAT_PID" 2>/dev/null || true
  fi
  if [[ -n "$REDIS_PID" ]]; then
    kill "$REDIS_PID" 2>/dev/null || true
    wait "$REDIS_PID" 2>/dev/null || true
  fi
  if [[ -n "$OPENCODE_PID" ]]; then
    kill "$OPENCODE_PID" 2>/dev/null || true
    wait "$OPENCODE_PID" 2>/dev/null || true
  fi
  if [[ -n "$ASSISTANT_PID" ]]; then
    kill "$ASSISTANT_PID" 2>/dev/null || true
    wait "$ASSISTANT_PID" 2>/dev/null || true
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

opencode_ready() {
  (cd "$BACKEND_DIR" && "$PYTHON_BIN" - <<'PY') >/dev/null 2>&1
import asyncio

from app.runtime.opencode_server import OpenCodeServerManager

raise SystemExit(0 if asyncio.run(OpenCodeServerManager().health()).healthy else 1)
PY
}

if [[ "${ASTRA_EXECUTOR_TYPE:-opencode_server}" == "opencode_server" ]]; then
  if ! opencode_ready; then
    if [[ -n "${ASTRA_OPENCODE_SERVER_URL:-}" ]]; then
      echo "无法连接 ASTRA_OPENCODE_SERVER_URL 指定的 OpenCode Server。" >&2
      exit 1
    fi
    echo "启动 OpenCode Server..."
    (cd "$BACKEND_DIR" && "$PYTHON_BIN" -m app.runtime.opencode_server) \
      >"$RUNTIME_DIR/opencode-server.log" 2>&1 &
    OPENCODE_PID=$!
    for _ in {1..150}; do
      if opencode_ready; then
        break
      fi
      sleep 0.2
    done
  fi
  if ! opencode_ready; then
    echo "OpenCode Server 启动失败，日志：$RUNTIME_DIR/opencode-server.log" >&2
    exit 1
  fi
fi

assistant_ready() {
  (cd "$BACKEND_DIR" && "$PYTHON_BIN" - <<'PY') >/dev/null 2>&1
import asyncio

from app.assistant.client import AssistantOpenCodeClient

try:
    raise SystemExit(0 if asyncio.run(AssistantOpenCodeClient().health()).get("healthy") else 1)
except Exception:
    raise SystemExit(1)
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

# 平台助手使用独立 OpenCode Server（默认 127.0.0.1:4097，目录 nexus-assistant）。
# 助手是增强能力：启动失败不阻塞核心运行时。
if [[ "${ASTRA_ASSISTANT_ENABLED:-true}" != "false" ]]; then
  if assistant_ready; then
    echo "助手 OpenCode Server: 已连接"
  elif [[ -n "${ASTRA_ASSISTANT_OPENCODE_URL:-}" ]]; then
    echo "无法连接 ASTRA_ASSISTANT_OPENCODE_URL 指定的助手 OpenCode Server（不影响平台核心功能）。" >&2
  else
    ASSISTANT_PORT="${ASTRA_ASSISTANT_OPENCODE_PORT:-4097}"
    echo "启动助手 OpenCode Server（nexus-assistant，:${ASSISTANT_PORT}）..."
    (cd "$BACKEND_DIR" && "$PYTHON_BIN" -m app.assistant.server) \
      >"$RUNTIME_DIR/assistant-opencode.log" 2>&1 &
    ASSISTANT_PID=$!
    for _ in {1..60}; do
      if assistant_ready; then
        break
      fi
      sleep 0.25
    done
    if assistant_ready; then
      echo "助手 OpenCode Server: 已连接"
    else
      echo "助手 OpenCode Server 启动失败（不影响平台核心功能），日志：$RUNTIME_DIR/assistant-opencode.log" >&2
    fi
  fi
fi

echo "Astra 调度控制面与 Agent 执行面已分离启动。按 Ctrl+C 停止。"
echo "Redis: 已连接"
if [[ "${ASTRA_EXECUTOR_TYPE:-opencode_server}" == "opencode_server" ]]; then
  echo "OpenCode Server: 已连接"
fi
cd "$BACKEND_DIR"
"$CELERY_BIN" -A app.runtime.celery_app:celery beat \
  --loglevel=INFO \
  --schedule "$RUNTIME_DIR/celerybeat-schedule" \
  >"$RUNTIME_DIR/celery-beat.log" 2>&1 &
BEAT_PID=$!
"$CELERY_BIN" -A app.runtime.celery_app:celery worker \
  --loglevel=INFO \
  --pool=solo \
  --queues=control \
  --hostname='astra-control@%h' \
  >"$RUNTIME_DIR/celery-control.log" 2>&1 &
CONTROL_PID=$!
"$CELERY_BIN" -A app.runtime.celery_app:celery worker \
  --loglevel=INFO \
  --pool=solo \
  --queues=agent \
  --hostname='astra-agent@%h'
