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
DEFAULT_UPGRADE_PACK_DIR="$REPO_ROOT/.runtime-cache/logs/value-proof/upgrade-pack"

if [ ! -x "$VENV/bin/python" ]; then
  bash "$ROOT/runtime/bootstrap_env.sh"
fi
PYTHON_BIN="${VALUE_PROOF_PYTHON:-$VENV/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

prepare_upgrade_pack_dir() {
  local target_dir="$1"
  mkdir -p "$target_dir"
  cp "$REPO_ROOT/contracts/proof/manual_baseline.example.json" "$target_dir/manual-baseline.json"
  "$PYTHON_BIN" - "$REPO_ROOT" "$target_dir" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]

repo_root = Path(sys.argv[1]).resolve()
target_dir = Path(sys.argv[2]).resolve()
contract = yaml.safe_load((repo_root / "contracts" / "proof" / "public_proof_contract.yaml").read_text(encoding="utf-8"))
pack = dict(contract.get("value_proof", {}).get("upgrade_pack", {}))
copied_file = str(pack.get("copied_file_name", "manual-baseline.json"))
manifest_name = str(pack.get("manifest_file_name", "upgrade-pack.json"))
payload = {
    "schema_version": 1,
    "pack_id": str(pack.get("pack_id", "value-proof-upgrade-pack")),
    "human_input_kind": str(pack.get("human_input_kind", "manual_baseline")),
    "template_status": str(pack.get("template_status", "template")),
    "recorded_input_status_required": str(pack.get("recorded_input_status_required", "recorded")),
    "current_claim_tier_cap": str(pack.get("current_claim_tier_cap", "smoke")),
    "recorded_input_unlocks_tier": str(pack.get("recorded_input_unlocks_tier", "interview")),
    "still_blocked_tiers_after_recorded_input": [str(item) for item in pack.get("still_blocked_tiers_after_recorded_input", [])],
    "prepare_command": str(pack.get("prepare_command", "bash tooling/runtime/run_value_proof.sh --prepare-upgrade-pack")),
    "rerun_command": f'bash tooling/runtime/run_value_proof.sh --manual-baseline-json "{target_dir / copied_file}"',
    "template_file": "contracts/proof/manual_baseline.example.json",
    "copied_file": copied_file,
    "fail_close": bool(pack.get("fail_close", True)),
}
(target_dir / manifest_name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(target_dir / "README.md").write_text(
    "\n".join(
        [
            "# Value Proof Upgrade Pack",
            "",
            "This pack is template-only. It does not count as recorded evidence yet.",
            "",
            f"- Machine-readable contract: `{manifest_name}`",
            f"- Current claim cap before real human input: `{payload['current_claim_tier_cap']}`",
            f"- Recorded input status required: `{payload['recorded_input_status_required']}`",
            f"- Recorded input unlocks tier: `{payload['recorded_input_unlocks_tier']}`",
            f"- Still blocked after a recorded baseline: `{', '.join(payload['still_blocked_tiers_after_recorded_input']) or 'none'}`",
            "",
            "1. Replace every placeholder in `manual-baseline.json` with a real human-timed baseline.",
            "2. Use the same dataset as `tests/fixtures/golden_input`.",
            "3. Read `upgrade-pack.json` before claiming anything stronger than smoke-tier.",
            "4. After editing, rerun:",
            "",
            "```bash",
            payload["rerun_command"],
            "```",
            "",
            "Fail-close rule: template/example content never counts as recorded evidence.",
            "A recorded manual baseline can unlock interview-tier wording, but it does not unlock public-tier proof on its own.",
        ]
    )
    + "\n",
    encoding="utf-8",
)
PY
  echo "value-proof upgrade pack prepared: $target_dir/manual-baseline.json"
  echo "value-proof upgrade pack contract: $target_dir/upgrade-pack.json"
  echo "next: edit the copied file with real human timing data, then run:"
  echo "bash tooling/runtime/run_value_proof.sh --manual-baseline-json \"$target_dir/manual-baseline.json\""
}

if [ "${1:-}" = "--prepare-upgrade-pack" ]; then
  target_dir="${2:-$DEFAULT_UPGRADE_PACK_DIR}"
  prepare_upgrade_pack_dir "$target_dir"
  exit 0
fi

if [ "${FILEMAN_IN_CONTAINER:-0}" != "1" ] && [ "${FILEMAN_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label value-proof -- bash tooling/runtime/run_value_proof.sh "$@"
fi

source "$VENV/bin/activate"
"$VENV/bin/python" "$ROOT/scripts/generate_value_proof_report.py" --root "$REPO_ROOT" "$@"
status=$?
if [ "$status" -eq 0 ]; then
  echo "value-proof guide: read docs/usage.md first, then docs/open_source_runbook.md."
fi
exit "$status"
