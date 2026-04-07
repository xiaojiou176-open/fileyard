#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"

DEFAULT_UPGRADE_ROOT="$REPO_ROOT/.runtime-cache/logs/proof-upgrade-pack"
CANONICAL_VALUE_PACK_DIR="$REPO_ROOT/.runtime-cache/logs/value-proof/upgrade-pack"
CANONICAL_AI_PACK_DIR="$REPO_ROOT/.runtime-cache/logs/ai-eval/upgrade-pack"
if [ "$#" -ge 2 ]; then
  value_pack_dir="$1"
  ai_pack_dir="$2"
else
  upgrade_root="${1:-$DEFAULT_UPGRADE_ROOT}"
  value_pack_dir="$upgrade_root/value-proof"
  ai_pack_dir="$upgrade_root/ai-eval"
fi

bash "$ROOT/runtime/run_value_proof.sh" --prepare-upgrade-pack "$value_pack_dir"
bash "$ROOT/gates/ai_eval_gate.sh" --prepare-upgrade-pack "$ai_pack_dir"

if [ "$value_pack_dir" != "$CANONICAL_VALUE_PACK_DIR" ]; then
  bash "$ROOT/runtime/run_value_proof.sh" --prepare-upgrade-pack "$CANONICAL_VALUE_PACK_DIR"
fi

if [ "$ai_pack_dir" != "$CANONICAL_AI_PACK_DIR" ]; then
  bash "$ROOT/gates/ai_eval_gate.sh" --prepare-upgrade-pack "$CANONICAL_AI_PACK_DIR"
fi

COMMON_ROOT="$(python3 - "$value_pack_dir" "$ai_pack_dir" <<'PY'
from pathlib import Path
import os
import sys

value_dir = Path(sys.argv[1]).resolve()
ai_dir = Path(sys.argv[2]).resolve()
print(os.path.commonpath([str(value_dir.parent), str(ai_dir.parent)]))
PY
)"

python3 - "$value_pack_dir" "$ai_pack_dir" "$COMMON_ROOT/proof-upgrade-pack.json" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

value_dir = Path(sys.argv[1]).resolve()
ai_dir = Path(sys.argv[2]).resolve()
output = Path(sys.argv[3]).resolve()
value_manifest = json.loads((value_dir / "upgrade-pack.json").read_text(encoding="utf-8"))
ai_manifest = json.loads((ai_dir / "upgrade-pack.json").read_text(encoding="utf-8"))
payload = {
    "schema_version": 1,
    "status": "template_only",
    "claim_readiness": "external_input_required",
    "packs": {
        "value_proof": value_manifest,
        "ai_eval": ai_manifest,
    },
}
output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "proof-upgrade-pack ready"
echo "- value proof baseline: $value_pack_dir/manual-baseline.json"
echo "- ai eval rubric: $ai_pack_dir/human-rubric.json"
echo "- combined pack contract: $COMMON_ROOT/proof-upgrade-pack.json"
echo "- canonical value proof baseline: $CANONICAL_VALUE_PACK_DIR/manual-baseline.json"
echo "- canonical ai eval rubric: $CANONICAL_AI_PACK_DIR/human-rubric.json"
echo "next:"
echo "1. fill the real human timing data in the manual baseline file"
echo "2. fill the real human review results in the rubric file"
echo "3. rerun:"
echo "bash tooling/runtime/run_value_proof.sh --manual-baseline-json \"$CANONICAL_VALUE_PACK_DIR/manual-baseline.json\""
echo "bash tooling/gates/ai_eval_gate.sh --human-rubric-json \"$CANONICAL_AI_PACK_DIR/human-rubric.json\""
