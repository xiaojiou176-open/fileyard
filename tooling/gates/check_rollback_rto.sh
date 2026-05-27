#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"
VENV="$(governance_runtime_venv_path "$REPO_ROOT")"

if [ "${FILEORGANIZE_IN_CONTAINER:-0}" != "1" ] && [ "${FILEORGANIZE_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label rollback-rto -- bash tooling/gates/check_rollback_rto.sh "$@"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "❌ check_rollback_rto: venv python not found: $VENV/bin/python" >&2
  exit 1
fi

BUDGET_MS="${FILEORGANIZE_ROLLBACK_RTO_BUDGET_MS:-3000}"
SUMMARY_PATH="$(governance_runtime_logs_path "$REPO_ROOT")/rollback-rto-baseline.json"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --budget-ms)
      BUDGET_MS="$2"
      shift 2
      ;;
    --summary)
      SUMMARY_PATH="$2"
      shift 2
      ;;
    *)
      echo "Usage: $0 [--budget-ms N] [--summary PATH]" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$(dirname "$SUMMARY_PATH")"

"$VENV/bin/python" - "$REPO_ROOT" "$VENV/bin/python" "$REPO_ROOT/apps/cli/fileorganize.py" "$BUDGET_MS" "$SUMMARY_PATH" <<'PY'
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo_root))
from packages.domain.rollback_integrity import _sign_rollback_record

py = Path(sys.argv[2]).resolve()
entry = Path(sys.argv[3]).resolve()
budget_ms = int(sys.argv[4])
summary_path = Path(sys.argv[5]).resolve()

run_id = "apply_20260303_000000_to"
hmac_key = "rollback-rto-baseline-key"
runtime_temp_root = repo_root / ".runtime-cache" / "temp"
runtime_temp_root.mkdir(parents=True, exist_ok=True)

with tempfile.TemporaryDirectory(prefix="rollback-rto-", dir=str(runtime_temp_root)) as tmp_dir:
    root = Path(tmp_dir).resolve()
    original = root / "orig.txt"
    moved = root / "moved.txt"
    original.write_text("before", encoding="utf-8")
    moved.write_text("after", encoding="utf-8")

    row = {
        "path": str(original),
        "new_path": str(moved),
        "media_type": "image",
        "run_id": run_id,
    }
    old_key = os.environ.get("FILEORGANIZE_ROLLBACK_HMAC_KEY")
    os.environ["FILEORGANIZE_ROLLBACK_HMAC_KEY"] = hmac_key
    try:
        row["rollback_sig"] = _sign_rollback_record(row, run_id)
    finally:
        if old_key is None:
            os.environ.pop("FILEORGANIZE_ROLLBACK_HMAC_KEY", None)
        else:
            os.environ["FILEORGANIZE_ROLLBACK_HMAC_KEY"] = old_key

    manifest = root / "manifest.jsonl"
    manifest.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    cmd = [
        str(py),
        str(entry),
        "rollback",
        "--manifest",
        str(manifest),
        "--allowed-root",
        str(root),
        "--strict-integrity",
        "--dry-run",
        "--overwrite",
    ]
    env = os.environ.copy()
    env["FILEORGANIZE_ROLLBACK_HMAC_KEY"] = hmac_key
    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(repo_root), env=env, capture_output=True, text=True)
    elapsed_ms = int((time.monotonic() - started) * 1000)

summary = {
    "metric": "cli.rollback.dry_run.duration_ms",
    "budget_ms": budget_ms,
    "actual_ms": elapsed_ms,
    "status": "pass" if elapsed_ms <= budget_ms and proc.returncode == 0 else "fail",
    "command": "fileorganize.py rollback --strict-integrity --dry-run --allowed-root <tmp>",
}
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))

if proc.returncode != 0:
    sys.stderr.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    raise SystemExit(proc.returncode)

if elapsed_ms > budget_ms:
    raise SystemExit(1)
PY

echo "✅ check_rollback_rto: passed (budget=${BUDGET_MS}ms)"
