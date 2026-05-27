#!/usr/bin/env bash
set -euo pipefail

HEARTBEAT_INTERVAL_SECONDS="${HEARTBEAT_INTERVAL_SECONDS:-30}"
PYTEST_MAX_DURATION_SECONDS="${PYTEST_MAX_DURATION_SECONDS:-0}"
PYTEST_HEARTBEAT_NAME="${PYTEST_HEARTBEAT_NAME:-pytest}"

if [ "$#" -lt 1 ]; then
  echo "Usage: bash tooling/scripts/run_pytest_with_heartbeat.sh <pytest command...>" >&2
  exit 2
fi

start_ts="$(date +%s)"
LOG_FILE="$(mktemp -t fileorganize-pytest-heartbeat.XXXXXX.log)"
(
  "$@"
) >"$LOG_FILE" 2>&1 &
test_pid=$!
last_progress=""
timed_out=0

terminate_test_process() {
  if [ -n "${test_pid:-}" ] && kill -0 "$test_pid" 2>/dev/null; then
    kill "$test_pid" 2>/dev/null || true
    sleep 1
    kill -s KILL "$test_pid" 2>/dev/null || true
    wait "$test_pid" 2>/dev/null || true
  fi
}

cleanup() {
  terminate_test_process
  rm -f "$LOG_FILE" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

while kill -0 "$test_pid" 2>/dev/null; do
  sleep "$HEARTBEAT_INTERVAL_SECONDS"
  if kill -0 "$test_pid" 2>/dev/null; then
    now_ts="$(date +%s)"
    elapsed=$((now_ts - start_ts))
    current_progress="$(tail -n 1 "$LOG_FILE" 2>/dev/null | tr -d '\r' || true)"
    if [ -z "$current_progress" ]; then
      current_progress="(no-output-yet)"
    fi
    if [ "$current_progress" != "$last_progress" ]; then
      last_progress="$current_progress"
    fi
    echo "[pytest-heartbeat] name=${PYTEST_HEARTBEAT_NAME} elapsed=${elapsed}s pid=${test_pid} progress=${last_progress}"

    if [ "$PYTEST_MAX_DURATION_SECONDS" -gt 0 ] && [ "$elapsed" -ge "$PYTEST_MAX_DURATION_SECONDS" ]; then
      echo "❌ ${PYTEST_HEARTBEAT_NAME} command exceeded PYTEST_MAX_DURATION_SECONDS=${PYTEST_MAX_DURATION_SECONDS}, terminating pid=${test_pid}" >&2
      timed_out=1
      kill "$test_pid" 2>/dev/null || true
      sleep 1
      kill -s KILL "$test_pid" 2>/dev/null || true
      break
    fi
  fi
done

set +e
wait "$test_pid"
rc=$?
set -e

cat "$LOG_FILE"

if [ "$timed_out" -eq 1 ]; then
  exit 124
fi
exit "$rc"
