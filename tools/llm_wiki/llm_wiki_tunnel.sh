#!/bin/sh
# Local LLM_WIKI_LOCAL_PORT -> remote 127.0.0.1:LLM_WIKI_REMOTE_PORT.
# LLM_WIKI_HOST is required. No host address is built into this script.
set -eu
: "${LLM_WIKI_HOST:?set LLM_WIKI_HOST to the llm_wiki SSH host}"
LOCAL_PORT="${LLM_WIKI_LOCAL_PORT:-19828}"
REMOTE_PORT="${LLM_WIKI_REMOTE_PORT:-18080}"
SSH_USER="${LLM_WIKI_SSH_USER:-root}"
SSH_KEY="${LLM_WIKI_SSH_KEY:-$HOME/.ssh/llmwiki_tunnel}"
while true; do
  ssh -N -i "$SSH_KEY" -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
      -o StrictHostKeyChecking=accept-new \
      -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
      "${SSH_USER}@${LLM_WIKI_HOST}"
  sleep 5
done
