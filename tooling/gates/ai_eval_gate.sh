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
DEFAULT_UPGRADE_PACK_DIR="$REPO_ROOT/.runtime-cache/logs/ai-eval/upgrade-pack"

if [ ! -x "$VENV/bin/python" ]; then
  bash "$ROOT/runtime/bootstrap_env.sh"
fi
PYTHON_BIN="${AI_EVAL_PYTHON:-$VENV/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

prepare_upgrade_pack_dir() {
  local target_dir="$1"
  mkdir -p "$target_dir"
  cp "$REPO_ROOT/contracts/ai/human_rubric.example.json" "$target_dir/human-rubric.json"
  "$PYTHON_BIN" - "$REPO_ROOT" "$target_dir" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]

repo_root = Path(sys.argv[1]).resolve()
target_dir = Path(sys.argv[2]).resolve()
contract = yaml.safe_load((repo_root / "contracts" / "proof" / "public_proof_contract.yaml").read_text(encoding="utf-8"))
pack = dict(contract.get("ai_eval", {}).get("upgrade_pack", {}))
copied_file = str(pack.get("copied_file_name", "human-rubric.json"))
manifest_name = str(pack.get("manifest_file_name", "upgrade-pack.json"))
payload = {
    "schema_version": 1,
    "pack_id": str(pack.get("pack_id", "ai-eval-upgrade-pack")),
    "human_input_kind": str(pack.get("human_input_kind", "human_rubric")),
    "template_status": str(pack.get("template_status", "template")),
    "recorded_input_status_required": str(pack.get("recorded_input_status_required", "recorded")),
    "current_claim_tier_cap": str(pack.get("current_claim_tier_cap", "smoke")),
    "recorded_input_unlocks_tier": str(pack.get("recorded_input_unlocks_tier", "public")),
    "prerequisite_before_recorded_input_unlocks": [str(item) for item in pack.get("prerequisite_before_recorded_input_unlocks", [])],
    "prepare_command": str(pack.get("prepare_command", "bash tooling/gates/ai_eval_gate.sh --prepare-upgrade-pack")),
    "rerun_command": f'bash tooling/gates/ai_eval_gate.sh --human-rubric-json "{target_dir / copied_file}"',
    "template_file": "contracts/ai/human_rubric.example.json",
    "copied_file": copied_file,
    "fail_close": bool(pack.get("fail_close", True)),
}
(target_dir / manifest_name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(target_dir / "README.md").write_text(
    "\n".join(
        [
            "# AI Eval Upgrade Pack",
            "",
            "This pack is template-only. It does not count as recorded human review yet.",
            "",
            f"- Machine-readable contract: `{manifest_name}`",
            f"- Current claim cap before real human input: `{payload['current_claim_tier_cap']}`",
            f"- Recorded input status required: `{payload['recorded_input_status_required']}`",
            f"- Recorded input unlocks tier: `{payload['recorded_input_unlocks_tier']}`",
            f"- Prerequisite before a stronger claim: `{', '.join(payload['prerequisite_before_recorded_input_unlocks']) or 'none'}`",
            "",
            "Prerequisite reminder:",
            "- A recorded human rubric still does not unlock a stronger tier unless `live_receipt.status == passed`.",
            "",
            "1. Replace every placeholder/example row in `human-rubric.json` with real human review results.",
            "2. Review the live-rubric output row by row before editing.",
            "3. Read `upgrade-pack.json` before claiming anything stronger than smoke-tier.",
            "4. After editing, rerun:",
            "",
            "```bash",
            payload["rerun_command"],
            "```",
            "",
            "Fail-close rule: template/example content never counts as recorded human rubric evidence.",
            "A recorded human rubric can strengthen live-quality claims only after the live receipt passes; it does not turn value-proof into public-grade proof by itself.",
        ]
    )
    + "\n",
    encoding="utf-8",
)
PY
  echo "ai-eval upgrade pack prepared: $target_dir/human-rubric.json"
  echo "ai-eval upgrade pack contract: $target_dir/upgrade-pack.json"
  echo "next: replace the example rows with real human review results, then run:"
  echo "bash tooling/gates/ai_eval_gate.sh --human-rubric-json \"$target_dir/human-rubric.json\""
}

if [ "${1:-}" = "--prepare-upgrade-pack" ]; then
  target_dir="${2:-$DEFAULT_UPGRADE_PACK_DIR}"
  prepare_upgrade_pack_dir "$target_dir"
  exit 0
fi

if [ "${MOVI_IN_CONTAINER:-0}" != "1" ] && [ "${MOVI_ALLOW_HOST_EXECUTION:-0}" != "1" ]; then
  exec bash "$ROOT/scripts/container_exec.sh" --label ai-eval -- bash tooling/gates/ai_eval_gate.sh "$@"
fi

"$VENV/bin/python" "$ROOT/scripts/run_ai_eval.py" --root "$REPO_ROOT" "$@"
status=$?
if [ "$status" -eq 0 ]; then
  echo "ai-eval guide: read live_receipt and evidence_tiers first, then docs/usage.md and docs/open_source_runbook.md."
fi
exit "$status"
