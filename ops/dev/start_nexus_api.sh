#!/usr/bin/env bash
# Nexus API on 8120. Chat model config comes from NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG.
# usage: ops/dev/start_nexus_api.sh [start|stop|status]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
. "$ROOT/ops/dev/load_env.sh"
ACTION="${1:-start}"
PIDFILE="${NEXUS_API_PIDFILE:-$ROOT/.astra/run/nexus-api.pid}"
LOG="${NEXUS_API_LOG:-/tmp/nexus-api.log}"
PY="$ROOT/services/nexus-api/.venv/bin/uvicorn"
mkdir -p "$(dirname "$PIDFILE")"
export NEXUS_DATA_DIR="${NEXUS_DATA_DIR:-$ROOT/services/nexus-api/data}"
export NEXUS_AGENTSCOPE_BASE_URL="${NEXUS_AGENTSCOPE_BASE_URL:-http://127.0.0.1:8000}"
export NEXUS_AGENTSCOPE_USER_ID="${NEXUS_AGENTSCOPE_USER_ID:-nexus}"
export NEXUS_TASK_MCP_URL="${NEXUS_TASK_MCP_URL:-http://127.0.0.1:8202/mcp}"
export NEXUS_CHAT_PROVIDER="${NEXUS_CHAT_PROVIDER:-openai}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.deepseek.com}"
export OPENAI_MODEL="${OPENAI_MODEL:-deepseek-flash}"
if [ -z "${OPENAI_API_KEY:-}" ] && [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  export OPENAI_API_KEY="$DEEPSEEK_API_KEY"
fi
stop_api() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill "$(cat "$PIDFILE")"
    rm -f "$PIDFILE"
  fi
}
case "$ACTION" in
  start)
    stop_api || true
    cd "$ROOT/services/nexus-api"
    setsid nohup "$PY" nexus_api.main:app --app-dir "$ROOT/services/nexus-api" --host 127.0.0.1 --port 8120 >>"$LOG" 2>&1 &
    echo $! >"$PIDFILE"
    echo "nexus api starting; log $LOG"
    ;;
  stop)
    stop_api
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "nexus api running pid $(cat "$PIDFILE")"
    else
      echo "nexus api is not running"
      exit 1
    fi
    ;;
  *)
    echo "usage: $0 [start|stop|status]" >&2
    exit 2
    ;;
esac
