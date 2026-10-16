#!/usr/bin/env bash
# AgentScope Agent Service on 8000.
# usage: ops/dev/start_agent_service.sh [start|stop|status]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
. "$ROOT/ops/dev/load_env.sh"
# shellcheck disable=SC1091
. "$ROOT/ops/dev/daemon.sh"
ACTION="${1:-start}"
PIDFILE="${AGENT_SERVICE_PIDFILE:-$ROOT/.astra/run/agent-service.pid}"
LOG="${AGENT_SERVICE_LOG:-/tmp/nexus-agent-service.log}"
PY="$ROOT/services/agent-service/.venv-agentscope/bin/python"
mkdir -p "$(dirname "$PIDFILE")"
export NEXUS_API_BASE="${NEXUS_API_BASE:-http://127.0.0.1:8120}"
export AGENTSCOPE_HOST="${AGENTSCOPE_HOST:-0.0.0.0}"
export AGENTSCOPE_PORT="${AGENTSCOPE_PORT:-8000}"
export AGENTSCOPE_REDIS_HOST="${AGENTSCOPE_REDIS_HOST:-127.0.0.1}"
export AGENTSCOPE_REDIS_PORT="${AGENTSCOPE_REDIS_PORT:-6379}"
export AGENTSCOPE_WORKSPACE_DIR="${AGENTSCOPE_WORKSPACE_DIR:-$ROOT/services/agent-service/data/workspaces}"
case "$ACTION" in
  start)
    stop_if_matches "$PIDFILE" "agent_service.py" || true
    cd "$ROOT"
    pid="$(detach "$PY" "$ROOT/services/agent-service/agent_service.py")"
    if wait_http "http://127.0.0.1:${AGENTSCOPE_PORT}/health" "$pid"; then
      echo "$pid" >"$PIDFILE"
      echo "agent service ready; log $LOG"
    else
      exit 1
    fi
    ;;
  stop)
    stop_if_matches "$PIDFILE" "agent_service.py"
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "agent service running pid $(cat "$PIDFILE")"
    else
      echo "agent service is not running"
      exit 1
    fi
    ;;
  *)
    echo "usage: $0 [start|stop|status]" >&2
    exit 2
    ;;
esac
