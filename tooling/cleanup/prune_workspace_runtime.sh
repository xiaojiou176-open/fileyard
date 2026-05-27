#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"
CONTRACT_PATH="$REPO_ROOT/contracts/runtime/filesystem_layout.yaml"
REPORT_HELPER="$ROOT/scripts/runtime_governance_report.py"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"

usage() {
  cat <<'EOF'
Usage:
  bash tooling/cleanup/prune_workspace_runtime.sh [--dry-run]

Applies workspace retention to:
  - FILEMAN_RUN_BUNDLE_ROOT
  - managed artifact roots under FILEMAN_ARTIFACT_ROOT

Never deletes:
  - FILEMAN_MANIFEST_ROOT
  - the workspace .fileman root itself
  - web_api/preferences
EOF
}

dry_run=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      dry_run=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "❌ prune_workspace_runtime: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

run_root="$(governance_run_bundle_root_path "$REPO_ROOT")"
artifact_root="$(governance_artifact_root_path "$REPO_ROOT")"
manifest_root="$(governance_manifest_root_path "$REPO_ROOT")"
python_bin="$(governance_runtime_venv_path "$REPO_ROOT")/bin/python"
if [ ! -x "$python_bin" ]; then
  python_bin="${PYTHON:-python3}"
fi

run_id="prune-workspace-runtime-$(date -u +%Y%m%dT%H%M%SZ)-$$"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
start_ts="$(date +%s)"
entries_json="$(mktemp)"
totals_json="$(mktemp)"
extra_json="$(mktemp)"
cleanup_tmp() {
  rm -f "$entries_json" "$totals_json" "$extra_json"
}
trap cleanup_tmp EXIT

"$python_bin" "$REPORT_HELPER" \
  --repo-root "$REPO_ROOT" \
  --command prune_workspace_runtime \
  --action-kind retention-prune \
  --bucket workspace_evidence \
  --target workspace_retention \
  --dry-run "$dry_run" \
  --run-id "$run_id" \
  --started-at "$started_at" \
  --start-ts "$start_ts" \
  --status start \
  --message "workspace retention prune started" \
  --ownership-class repo_workspace \
  --reclaim-class workspace_retention >/dev/null

"$python_bin" - "$CONTRACT_PATH" "$run_root" "$artifact_root" "$manifest_root" "$dry_run" "$entries_json" "$totals_json" "$extra_json" <<'PY'
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

import yaml  # type: ignore[import-untyped]

contract_path = Path(sys.argv[1])
run_root = Path(sys.argv[2]).expanduser()
artifact_root = Path(sys.argv[3]).expanduser()
manifest_root = Path(sys.argv[4]).expanduser()
dry_run = sys.argv[5] == "1"
entries_path = Path(sys.argv[6])
totals_path = Path(sys.argv[7])
extra_path = Path(sys.argv[8])

contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
if not isinstance(contract, dict):
    raise SystemExit(f"invalid yaml: {contract_path}")
retention = dict(contract.get("retention", {}))
workspace_runs_days = float(retention.get("workspace_runs_days", 14))
workspace_runs_keep_latest = int(retention.get("workspace_runs_keep_latest", 50))
workspace_artifacts_days = float(retention.get("workspace_artifacts_days", 14))
workspace_failed_artifacts_days = float(retention.get("workspace_failed_artifacts_days", 30))
now = time.time()


def _age_days(path: Path) -> float:
    return max(0.0, (now - path.stat().st_mtime) / 86400.0)


def _size_kib(path: Path) -> int:
    if not path.exists():
        return 0
    return int(subprocess.check_output(["du", "-sk", str(path)], text=True).split()[0])


def _iter_direct_children(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(
        root.iterdir(),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def _extract_status_tokens(obj: object, out: set[str]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in {"status", "overall_status", "phase_label"} and isinstance(value, str):
                out.add(value.strip().lower())
            _extract_status_tokens(value, out)
    elif isinstance(obj, list):
        for item in obj:
            _extract_status_tokens(item, out)


def _path_is_failure_like(path: Path) -> bool:
    failure_tokens = {"fail", "failed", "error", "cancelled", "canceled"}
    success_tokens = {"pass", "passed", "succeeded", "success", "ok"}
    json_files = []
    for pattern in ("job.json", "summary.json"):
        json_files.extend(path.rglob(pattern))
    json_files.extend(p for p in path.rglob("*.json") if p.name not in {"job.json", "summary.json"})
    for candidate in json_files[:20]:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        tokens: set[str] = set()
        _extract_status_tokens(payload, tokens)
        if tokens & failure_tokens:
            return True
        if tokens & success_tokens:
            continue
    return False


run_candidates: list[Path] = []
if run_root.exists():
    run_dirs = [path for path in _iter_direct_children(run_root) if path.is_dir()]
    protected = set(run_dirs[:workspace_runs_keep_latest])
    for path in run_dirs:
        if path in protected:
            continue
        if _age_days(path) > workspace_runs_days:
            run_candidates.append(path)

artifact_candidates: list[Path] = []
managed_roots = [
    (artifact_root / "ai-eval", True),
    (artifact_root / "value-proof", True),
    (artifact_root / "report", False),
    (artifact_root / "rollback", True),
    (artifact_root / "web_api" / "jobs", True),
    (artifact_root / "web_api" / "csv", False),
    (artifact_root / "web_api" / "uploads", False),
]
for root, failure_aware in managed_roots:
    if not root.exists():
        continue
    for path in _iter_direct_children(root):
        if not path.exists():
            continue
        threshold_days = workspace_artifacts_days
        if failure_aware and _path_is_failure_like(path):
            threshold_days = workspace_failed_artifacts_days
        if _age_days(path) > threshold_days:
            artifact_candidates.append(path)

total_kib = sum(_size_kib(path) for path in run_candidates + artifact_candidates)
action = "would prune" if dry_run else "pruned"
print(f"{action} workspace runtime candidates total_kib={total_kib}")
print(f"- protected_manifests_root={manifest_root}")
entries: list[dict[str, object]] = []
for path in run_candidates:
    size_kib = _size_kib(path)
    entries.append(
        {
            "path_or_object": str(path),
            "size_before_kib": size_kib,
            "size_after_kib": size_kib if dry_run else 0,
            "reclaimed_kib": 0 if dry_run else size_kib,
            "ownership_class": "repo_workspace",
            "reclaim_class": "workspace_run_retention",
            "protected": False,
            "exists_or_present": path.exists(),
            "status": "candidate",
        }
    )
    print(f"- run {path} size_kib={size_kib} age_days={_age_days(path):.1f}")
for path in artifact_candidates:
    size_kib = _size_kib(path)
    entries.append(
        {
            "path_or_object": str(path),
            "size_before_kib": size_kib,
            "size_after_kib": size_kib if dry_run else 0,
            "reclaimed_kib": 0 if dry_run else size_kib,
            "ownership_class": "repo_workspace",
            "reclaim_class": "workspace_artifact_retention",
            "protected": False,
            "exists_or_present": path.exists(),
            "status": "candidate",
        }
    )
    print(f"- artifact {path} size_kib={size_kib} age_days={_age_days(path):.1f}")

entries_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
totals_path.write_text(
    json.dumps(
        {
            "candidate_kib": total_kib,
            "reclaimed_kib": 0 if dry_run else total_kib,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
extra_path.write_text(
    json.dumps(
        {
            "protected_manifests_root": str(manifest_root),
            "dry_run": dry_run,
            "run_candidate_count": len(run_candidates),
            "artifact_candidate_count": len(artifact_candidates),
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

if dry_run:
    raise SystemExit(0)

for path in run_candidates + artifact_candidates:
    if not path.exists():
        continue
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
PY
rc=$?

status="success"
message="workspace retention prune completed"
if [ "$rc" -ne 0 ]; then
  status="fail"
  message="workspace retention prune failed"
fi

"$python_bin" "$REPORT_HELPER" \
  --repo-root "$REPO_ROOT" \
  --command prune_workspace_runtime \
  --action-kind retention-prune \
  --bucket workspace_evidence \
  --target workspace_retention \
  --dry-run "$dry_run" \
  --run-id "$run_id" \
  --started-at "$started_at" \
  --start-ts "$start_ts" \
  --status "$status" \
  --message "$message" \
  --ownership-class repo_workspace \
  --reclaim-class workspace_retention \
  --entries-json "$entries_json" \
  --totals-json "$totals_json" \
  --extra-json "$extra_json" >/dev/null || true

exit "$rc"
