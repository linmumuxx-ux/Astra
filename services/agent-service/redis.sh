#!/usr/bin/env bash
# 启动 AgentScope 使用的 Redis。已有 PONG 时不再启动第二份。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PORT="${AGENTSCOPE_REDIS_PORT:-6379}"

if command -v redis-cli >/dev/null 2>&1 && redis-cli -p "$PORT" ping >/dev/null 2>&1; then
  echo "redis already answering on port ${PORT}"
  exit 0
fi

if command -v docker >/dev/null 2>&1; then
  docker compose -f "$ROOT/services/agent-service/docker-compose.yml" up -d
  exit 0
fi

if ! command -v redis-server >/dev/null 2>&1; then
  echo "没有 docker，也没有 redis-server。请安装其中之一后再运行 services/agent-service/redis.sh。" >&2
  exit 1
fi

DATA="$ROOT/services/agent-service/data/redis"
mkdir -p "$DATA"
redis-server \
  --daemonize yes \
  --bind 127.0.0.1 \
  --port "$PORT" \
  --protected-mode yes \
  --dir "$DATA" \
  --pidfile "$DATA/redis.pid" \
  --dbfilename dump.rdb
redis-cli -p "$PORT" ping
