#!/usr/bin/env bash
# Task MCP on ASTRA_TASK_MCP_PORT (default 8202).
# usage: ops/dev/start_task_mcp.sh [start|stop|status]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
. "$ROOT/ops/dev/load_env.sh"
# shellcheck disable=SC1091
. "$ROOT/ops/dev/daemon.sh"
ACTION="${1:-start}"
PIDFILE="${TASK_MCP_PIDFILE:-$ROOT/.astra/run/task-mcp.pid}"
LOG="${TASK_MCP_LOG:-/tmp/nexus-task-mcp.log}"
PORT="${ASTRA_TASK_MCP_PORT:-8202}"
BIN="$ROOT/services/task-platform/.venv/bin/astra-task-mcp"
PY="$ROOT/services/task-platform/.venv/bin/python"
mkdir -p "$(dirname "$PIDFILE")"
export ASTRA_TASK_MCP_HOST="${ASTRA_TASK_MCP_HOST:-127.0.0.1}"
export ASTRA_TASK_MCP_PORT="$PORT"
case "$ACTION" in
  start)
    if [ -x "$BIN" ]; then
      CMD=("$BIN")
    elif [ -x "$PY" ]; then
      CMD=("$PY" -c "from app.task_mcp import main; main()")
    else
      echo "missing $BIN; install services/task-platform first" >&2
      exit 1
    fi
    stop_if_matches "$PIDFILE" "task_mcp" || true
    cd "$ROOT/services/task-platform"
    pid="$(detach "${CMD[@]}")"
    if wait_http "http://127.0.0.1:${PORT}/mcp" "$pid"; then
      echo "$pid" >"$PIDFILE"
      echo "task mcp ready on ${ASTRA_TASK_MCP_HOST}:${PORT}; log $LOG"
    else
      exit 1
    fi
    ;;
  stop)
    stop_if_matches "$PIDFILE" "task_mcp"
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "task mcp running pid $(cat "$PIDFILE") port $PORT"
    else
      echo "task mcp is not running"
      exit 1
    fi
    ;;
  *)
    echo "usage: $0 [start|stop|status]" >&2
    exit 2
    ;;
esac
