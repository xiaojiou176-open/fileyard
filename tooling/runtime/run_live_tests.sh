#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"
LIVE_TEST_PID=""
LIVE_COVERAGE_FILE=""
LIVE_PLAYWRIGHT_CACHE_DIR=""

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"

VENV="$(governance_runtime_venv_path "$REPO_ROOT")"
RUNTIME_ENV_FILE="$(governance_runtime_env_file_path "$REPO_ROOT")"

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" != "1" ] && [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label run-live-tests -- bash tooling/runtime/run_live_tests.sh "$@"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ run_live_tests: venv python not found: $VENV/bin/python" >&2
  exit 1
fi

cleanup_live_test_process() {
  if [ -n "${LIVE_TEST_PID:-}" ] && kill -0 "$LIVE_TEST_PID" 2>/dev/null; then
    kill "$LIVE_TEST_PID" 2>/dev/null || true
    sleep 1
    kill -s KILL "$LIVE_TEST_PID" 2>/dev/null || true
    wait "$LIVE_TEST_PID" 2>/dev/null || true
  fi
  if [ -n "${LIVE_COVERAGE_FILE:-}" ]; then
    rm -f "$LIVE_COVERAGE_FILE" "$LIVE_COVERAGE_FILE-shm" "$LIVE_COVERAGE_FILE-wal" || true
  fi
  if [ -n "${LIVE_PLAYWRIGHT_CACHE_DIR:-}" ]; then
    rm -rf "$LIVE_PLAYWRIGHT_CACHE_DIR" || true
  fi
}
trap cleanup_live_test_process EXIT INT TERM

read_runtime_env_value() {
  local name="$1"
  "$VENV/bin/python" - "$RUNTIME_ENV_FILE" "$name" <<'PY'
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
name = sys.argv[2]
if not env_path.exists():
    raise SystemExit(0)
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() != name:
        continue
    parsed = value.strip()
    if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {'"', "'"}:
        parsed = parsed[1:-1]
    print(parsed.strip())
    raise SystemExit(0)
PY
}

resolve_var_prefer_runtime_env() {
  local name="$1"
  local default="${2:-}"
  local value=""
  value="${!name:-}"
  if [ -z "$value" ]; then
    value="$(read_runtime_env_value "$name")"
  fi
  if [ -z "$value" ]; then
    value="$default"
  fi
  export "$name=$value"
}

resolve_var_prefer_env_then_runtime_env() {
  local name="$1"
  local default="${2:-}"
  local value="${!name:-}"
  if [ -z "$value" ]; then
    value="$(read_runtime_env_value "$name")"
  fi
  if [ -z "$value" ]; then
    value="$default"
  fi
  export "$name=$value"
}

validate_url() {
  "$VENV/bin/python" - "$1" <<'PY'
import sys
import ipaddress
from urllib.parse import urlparse

url = sys.argv[1].strip()
p = urlparse(url)
host = (p.hostname or "").strip().strip(".").lower()
blocked_hosts = {
    "example.com",
    "www.example.com",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
}
blocked_suffixes = (".local", ".localhost", ".test", ".invalid", ".example")
ok = p.scheme == "https" and bool(p.netloc)
if not ok or not host:
    raise SystemExit(2)
if host in blocked_hosts or host.endswith(blocked_suffixes):
    raise SystemExit(2)
try:
    addr = ipaddress.ip_address(host)
except ValueError:
    raise SystemExit(0)
if any(
    (
        addr.is_private,
        addr.is_loopback,
        addr.is_link_local,
        addr.is_multicast,
        addr.is_reserved,
        addr.is_unspecified,
    )
):
    raise SystemExit(2)
PY
}

looks_like_placeholder_key() {
  local value="$1"
  if [ ${#value} -lt 20 ]; then
    return 0
  fi
  if printf '%s' "$value" | grep -Eqi '(^|[^[:alnum:]])(dummy|test|mock|fake|placeholder|sample|changeme|replaceme)([^[:alnum:]]|$)'; then
    return 0
  fi
  return 1
}

classify_live_failure() {
  local log_file="$1"
  if [ ! -f "$log_file" ]; then
    echo "unknown"
    return 0
  fi
  local helper="$ROOT/scripts/live_test_failure_classifier.py"
  if [ -f "$helper" ]; then
    "$VENV/bin/python" "$helper" --log-file "$log_file"
    return 0
  fi
  # Secondary path when helper is unavailable: business takes precedence over network.
  if grep -Eqi "LIVE_ERROR_CLASS=business|AssertionError|preflight failed|request not ok|server error|empty page title|empty body text|missing|invalid format|playwright\\._impl\\._errors\\.TimeoutError|Locator\\.[A-Za-z]+: Timeout|waiting for get_by_role" "$log_file"; then
    echo "business"
    return 0
  fi
  if grep -Eqi "LIVE_ERROR_CLASS=network-jitter|ECONN|ENOTFOUND|EAI_AGAIN|net::|Connection reset|connection refused|ERR_NETWORK_CHANGED|ERR_NAME_NOT_RESOLVED|dns|name resolution|unreachable" "$log_file"; then
    echo "network-jitter"
    return 0
  fi
  if grep -Eqi "LIVE_ERROR_CLASS=network-timeout|timed out|timeout|upstream unavailable|service unavailable|gateway timeout|deadline exceeded|502|503|504" "$log_file"; then
    echo "network-timeout"
    return 0
  fi
  echo "unknown"
}

is_retryable_live_failure_class() {
  local failure_class="${1:-unknown}"
  [ "$failure_class" = "network-timeout" ] || [ "$failure_class" = "network-jitter" ]
}

sync_live_attempt_artifacts() {
  local src_log_file="$1"
  local src_junit_file="$2"
  local dest_log_file="$3"
  local dest_junit_file="$4"

  if [ -f "$src_log_file" ]; then
    cp "$src_log_file" "$dest_log_file"
  fi
  if [ -f "$src_junit_file" ]; then
    cp "$src_junit_file" "$dest_junit_file"
  fi
}

run_live_pytest_with_heartbeat() {
  local log_file="$1"
  local junit_file="$2"
  shift 2

  local start_ts
  local last_progress=""
  local current_progress=""
  local stalled_on_terminal_progress=0
  start_ts="$(date +%s)"
  : >"$log_file"
  PYTHONUNBUFFERED=1 "$VENV/bin/python" -m pytest -q -s -m "live_llm or live_browser" -k "not env_preflight" --maxfail=1 \
    --strict-config \
    --strict-markers \
    --junitxml="$junit_file" "$@" >"$log_file" 2>&1 &
  local test_pid=$!
  LIVE_TEST_PID="$test_pid"
  while kill -0 "$test_pid" 2>/dev/null; do
    local now_ts elapsed
    now_ts="$(date +%s)"
    elapsed="$((now_ts - start_ts))"
    if [ "$elapsed" -ge "${LIVE_MAX_DURATION_SECONDS}" ]; then
      echo "❌ live tests exceeded LIVE_MAX_DURATION_SECONDS=${LIVE_MAX_DURATION_SECONDS}, terminating pid=${test_pid}" >&2
      kill "$test_pid" 2>/dev/null || true
      sleep 1
      kill -s KILL "$test_pid" 2>/dev/null || true
      break
    fi
    current_progress="$(tail -n 1 "$log_file" 2>/dev/null | tr -d '\r' || true)"
    if [ -z "$current_progress" ]; then
      current_progress="(no-output-yet)"
    fi
    if [ "$current_progress" = "$last_progress" ]; then
      stalled_on_terminal_progress=$((stalled_on_terminal_progress + 1))
    else
      stalled_on_terminal_progress=0
      last_progress="$current_progress"
    fi
    printf '[live-heartbeat] ts=%s elapsed=%ss pid=%s model=%s host=%s progress=%s\n' \
      "$(date '+%Y-%m-%d %H:%M:%S')" "${elapsed}" "${test_pid}" "${GEMINI_MODEL}" "${host}" "${last_progress}"
    if printf '%s' "$last_progress" | grep -Eq '[0-9]+ failed, [0-9]+ passed|short test summary info'; then
      if [ "$stalled_on_terminal_progress" -ge 3 ]; then
        echo "⚠️ live tests appear stuck after pytest summary, terminating pid=${test_pid}" >&2
        kill "$test_pid" 2>/dev/null || true
        sleep 1
        kill -s KILL "$test_pid" 2>/dev/null || true
        break
      fi
    fi
    sleep "${LIVE_HEARTBEAT_INTERVAL_SECONDS}"
  done
  wait "$test_pid"
  local rc=$?
  LIVE_TEST_PID=""
  return "$rc"
}

resolve_var_prefer_env_then_runtime_env GEMINI_MODEL ""
resolve_var_prefer_env_then_runtime_env FILEORGANIZE_LIVE_TEST_URL ""
resolve_var_prefer_runtime_env GEMINI_API_KEY ""
resolve_var_prefer_runtime_env LIVE_HEARTBEAT_INTERVAL_SECONDS "20"
resolve_var_prefer_runtime_env LIVE_MAX_DURATION_SECONDS "600"
resolve_var_prefer_runtime_env LIVE_MAX_RETRIES "2"

if ! printf '%s' "${LIVE_MAX_RETRIES}" | grep -Eq '^[0-9]+$'; then
  echo "❌ run_live_tests: LIVE_MAX_RETRIES must be an integer between 1 and 2, got ${LIVE_MAX_RETRIES}" >&2
  exit 1
fi
if [ "${LIVE_MAX_RETRIES}" -lt 1 ]; then
  LIVE_MAX_RETRIES=1
fi
if [ "${LIVE_MAX_RETRIES}" -gt 2 ]; then
  LIVE_MAX_RETRIES=2
fi

if [ -z "${GEMINI_API_KEY}" ]; then
  echo "❌ run_live_tests: GEMINI_API_KEY is required for live_llm tests" >&2
  echo "Tip: set GEMINI_API_KEY in $RUNTIME_ENV_FILE or current shell env." >&2
  exit 1
fi

if [ -z "${GEMINI_MODEL}" ]; then
  echo "❌ run_live_tests: GEMINI_MODEL is required for live tests" >&2
  echo "Tip: set GEMINI_MODEL in $RUNTIME_ENV_FILE or current shell env." >&2
  exit 1
fi

if [ -z "${FILEORGANIZE_LIVE_TEST_URL}" ]; then
  echo "❌ run_live_tests: FILEORGANIZE_LIVE_TEST_URL is required for live browser tests" >&2
  echo "Tip: set FILEORGANIZE_LIVE_TEST_URL in $RUNTIME_ENV_FILE or current shell env." >&2
  exit 1
fi

if looks_like_placeholder_key "${GEMINI_API_KEY}"; then
  echo "❌ run_live_tests: GEMINI_API_KEY looks like placeholder/dummy key (or too short)." >&2
  exit 1
fi

if ! validate_url "${FILEORGANIZE_LIVE_TEST_URL}"; then
  echo "❌ run_live_tests: FILEORGANIZE_LIVE_TEST_URL must be an absolute https URL to a real external host." >&2
  echo "Current value: ${FILEORGANIZE_LIVE_TEST_URL}" >&2
  exit 1
fi

if ! printf '%s' "${GEMINI_MODEL}" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$'; then
  echo "❌ run_live_tests: GEMINI_MODEL has invalid format: ${GEMINI_MODEL}" >&2
  exit 1
fi
if ! printf '%s' "${GEMINI_MODEL}" | grep -Eqi '^gemini-'; then
  echo "❌ run_live_tests: GEMINI_MODEL must start with gemini- (Gemini-only policy)." >&2
  exit 1
fi

export FILEORGANIZE_RUN_LIVE_TESTS=1
export FILEORGANIZE_RUN_WEBUI_E2E=1
LIVE_COVERAGE_FILE="${FILEORGANIZE_LIVE_COVERAGE_FILE:-$(governance_runtime_ci_path "$REPO_ROOT")/.coverage-live-$$}"
export COVERAGE_FILE="$LIVE_COVERAGE_FILE"
rm -f "$LIVE_COVERAGE_FILE" "$LIVE_COVERAGE_FILE-shm" "$LIVE_COVERAGE_FILE-wal" || true
echo "==> Isolated live coverage data file: $LIVE_COVERAGE_FILE"

LIVE_PLAYWRIGHT_CACHE_DIR="${LIVE_PLAYWRIGHT_BROWSERS_PATH:-$(governance_runtime_temp_path "$REPO_ROOT")/playwright-live-$$}"
export PLAYWRIGHT_BROWSERS_PATH="$LIVE_PLAYWRIGHT_CACHE_DIR"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
echo "==> Isolated live Playwright cache dir: $PLAYWRIGHT_BROWSERS_PATH"

echo "==> Ensuring Playwright WebUI/browser binaries are installed"
"$VENV/bin/python" -m playwright install chromium webkit

echo "==> Stage 1/2: preflight live tests"
"$VENV/bin/python" -m pytest -q --maxfail=1 \
  --strict-config \
  --strict-markers \
  tests/e2e/test_live_llm_integration.py::test_live_llm_env_preflight \
  tests/e2e/test_live_external_site_playwright.py::test_live_browser_env_preflight \
  tests/e2e/test_live_webui_playwright.py::test_live_webui_env_preflight

echo "==> Stage 2/2: full live tests with heartbeat"
set +e
LOG_DIR="$(governance_runtime_ci_path "$REPO_ROOT")"
LOG_FILE="$LOG_DIR/live-tests.log"
JUNIT_FILE="$LOG_DIR/live-tests-junit.xml"
mkdir -p "$LOG_DIR"
host="$("$VENV/bin/python" - "${FILEORGANIZE_LIVE_TEST_URL}" <<'PY'
from urllib.parse import urlparse
import sys
print((urlparse(sys.argv[1]).hostname or "").strip())
PY
)"

exit_code=1
attempt=1
while [ "$attempt" -le "${LIVE_MAX_RETRIES}" ]; do
  ATTEMPT_LOG_FILE="$LOG_DIR/live-tests-attempt-${attempt}.log"
  ATTEMPT_JUNIT_FILE="$LOG_DIR/live-tests-attempt-${attempt}.xml"
  if [ "$attempt" -gt 1 ]; then
    echo "==> Stage 2/2 retry ${attempt}/${LIVE_MAX_RETRIES}"
  fi
  run_live_pytest_with_heartbeat "$ATTEMPT_LOG_FILE" "$ATTEMPT_JUNIT_FILE" "$@"
  exit_code=$?
  sync_live_attempt_artifacts "$ATTEMPT_LOG_FILE" "$ATTEMPT_JUNIT_FILE" "$LOG_FILE" "$JUNIT_FILE"
  if [ "$exit_code" -eq 0 ]; then
    break
  fi
  failure_class="$(classify_live_failure "$ATTEMPT_LOG_FILE")"
  echo "⚠️ live tests failed on attempt ${attempt}/${LIVE_MAX_RETRIES} (class=${failure_class})" >&2
  if ! is_retryable_live_failure_class "$failure_class" || [ "$attempt" -ge "${LIVE_MAX_RETRIES}" ]; then
    break
  fi
  retry_wait_s="$("$VENV/bin/python" - "$attempt" <<'PY'
import random
import sys

attempt = max(1, int(sys.argv[1]))
base = min(8.0, float(2 * attempt))
jitter = random.uniform(0.0, 0.75)
print(f"{base + jitter:.2f}")
PY
)"
  echo "⏳ live retry backoff: class=${failure_class} attempt=${attempt}/${LIVE_MAX_RETRIES} wait=${retry_wait_s}s" >&2
  sleep "$retry_wait_s"
  attempt=$((attempt + 1))
done
set -e
if [ "$exit_code" -ne 0 ]; then
  failure_class="$(classify_live_failure "$LOG_FILE")"
  echo "❌ live tests failed (exit=${exit_code}). Tail of ${LOG_FILE}:" >&2
  tail -n 120 "$LOG_FILE" >&2 || true
  echo "---- live failure classification ----" >&2
  echo "class=${failure_class}" >&2
  echo "---- live tests short summary ----" >&2
  grep -E "^(FAILED|ERROR|E[[:space:]]+|=+ short test summary info =+)" "$LOG_FILE" >&2 || true
else
  echo "✅ live tests passed. Log: ${LOG_FILE} JUnit: ${JUNIT_FILE}"
fi
exit "$exit_code"
