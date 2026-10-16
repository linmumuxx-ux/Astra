#!/usr/bin/env bash
# Shared start/stop helpers. macOS has no setsid; fall back to nohup.
# shellcheck shell=bash

detach() {
  if command -v setsid >/dev/null 2>&1; then
    setsid nohup "$@" >>"$LOG" 2>&1 &
  else
    nohup "$@" >>"$LOG" 2>&1 &
  fi
  echo "$!"
}

run_and_wait() {
  if command -v setsid >/dev/null 2>&1; then
    setsid nohup "$@" >>"$LOG" 2>&1 &
  else
    nohup "$@" >>"$LOG" 2>&1 &
  fi
  wait "$!"
}

wait_http() {
  local url="$1" pid="$2" attempts=150 i code
  shift 2
  if [ $# -gt 0 ] && [[ "$1" =~ ^[0-9]+$ ]]; then
    attempts="$1"
    shift
  fi
  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to check $url" >&2
    kill "$pid" 2>/dev/null || true
    return 1
  fi
  for i in $(seq 1 "$attempts"); do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "process $pid exited before ready; log $LOG" >&2
      return 1
    fi
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 1 "$@" "$url" || true)"
    case "$code" in
      2[0-9][0-9]) return 0 ;;
    esac
    sleep 0.2
  done
  echo "not ready: $url; log $LOG" >&2
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  return 1
}

process_command() {
  ps -p "$1" -o args= 2>/dev/null || ps -p "$1" -o command= 2>/dev/null || true
}

stop_if_matches() {
  local pidfile="$1" token="$2" pid cmd
  if [ ! -f "$pidfile" ]; then
    return 0
  fi
  pid="$(cat "$pidfile")"
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pidfile"
    return 0
  fi
  cmd="$(process_command "$pid")"
  case "$cmd" in
    *"$token"*)
      kill "$pid"
      rm -f "$pidfile"
      ;;
    *)
      echo "refusing to stop pid $pid; command does not match $token" >&2
      rm -f "$pidfile"
      return 1
      ;;
  esac
}
