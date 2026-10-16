# Shared by the local start scripts. Source this file; do not execute it.
# Reads one env file: $ENV_FILE, otherwise ops/env/.env, otherwise .env.
if [ -z "${ROOT:-}" ]; then
  echo "ROOT is not set" >&2
  return 1 2>/dev/null || exit 1
fi
if [ -z "${ENV_FILE:-}" ]; then
  if [ -f "$ROOT/ops/env/.env" ]; then
    ENV_FILE="$ROOT/ops/env/.env"
  elif [ -f "$ROOT/.env" ]; then
    ENV_FILE="$ROOT/.env"
  else
    echo "missing env file: $ROOT/ops/env/.env" >&2
    return 1 2>/dev/null || exit 1
  fi
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "env file not found: $ENV_FILE" >&2
  return 1 2>/dev/null || exit 1
fi
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
