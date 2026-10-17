# Shared by the local start scripts. Source this file; do not execute it.
# Reads one env file: $ENV_FILE when set, otherwise ops/env/.env.
if [ -z "${ROOT:-}" ]; then
  echo "ROOT is not set" >&2
  return 1 2>/dev/null || exit 1
fi
if [ -z "${ENV_FILE:-}" ]; then
  ENV_FILE="$ROOT/ops/env/.env"
  if [ ! -f "$ENV_FILE" ]; then
    echo "missing env file: $ENV_FILE" >&2
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
