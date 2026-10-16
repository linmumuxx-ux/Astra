#!/usr/bin/env bash
# Task platform supervisor: Task API 8100, gateway 8110, Celery, OpenCode, Nexus Web 5174.
# usage: ops/dev/start_astra.sh [start|restart|stop|status]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
. "$ROOT/ops/dev/load_env.sh"
ACTION="${1:-start}"
export PATH="${HOME}/.local/bin:${PATH}"
export ASTRA_GATEWAY_PROBE_TIMEOUT_SECONDS="${ASTRA_GATEWAY_PROBE_TIMEOUT_SECONDS:-30}"
export ASTRA_MCP_TRANSPORT="${ASTRA_MCP_TRANSPORT:-streamable-http}"
export ASTRA_REDIS_URL="${ASTRA_REDIS_URL:-redis://127.0.0.1:6379/0}"
export ASTRA_OUTBOX_INTERVAL="${ASTRA_OUTBOX_INTERVAL:-2}"
export ASTRA_OUTBOX_RETRY_SECONDS="${ASTRA_OUTBOX_RETRY_SECONDS:-5}"
export ASTRA_OPENCODE_MODEL="${ASTRA_OPENCODE_MODEL:-opencode/cat-jam-free}"
export ASTRA_NEXUS_API_BASE="${ASTRA_NEXUS_API_BASE:-http://127.0.0.1:8120}"
export ASTRA_AGENTSCOPE_BASE_URL="${ASTRA_AGENTSCOPE_BASE_URL:-http://127.0.0.1:8000}"
export ASTRA_AGENTSCOPE_USER_ID="${ASTRA_AGENTSCOPE_USER_ID:-nexus}"
export ASTRA_LLM_WIKI_API_BASE_URL="${ASTRA_LLM_WIKI_API_BASE_URL:-http://127.0.0.1:19828/api/v1}"
PY="$ROOT/services/task-platform/.venv/bin/python"
LOG="${ASTRA_LOG:-/tmp/nexus-task-platform.log}"
cd "$ROOT/services/task-platform"
case "$ACTION" in
  start)
    setsid nohup "$PY" "$ROOT/ops/dev/astra_service.py" dev start >>"$LOG" 2>&1 &
    echo "task platform starting; log $LOG"
    ;;
  restart|stop|status)
    "$PY" "$ROOT/ops/dev/astra_service.py" dev "$ACTION"
    ;;
  *)
    echo "usage: $0 [start|restart|stop|status]" >&2
    exit 2
    ;;
esac
