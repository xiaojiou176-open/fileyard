#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

DEFAULT_OUTPUT = ".runtime-cache/logs/value-proof/summary.json"
DEFAULT_DATASET = "tests/fixtures/golden_input"
DEFAULT_THRESHOLD = 0.6
DEFAULT_MANUAL_BASELINE_STATUS = "manual_capture_required"
PUBLIC_PROOF_CONTRACT = "contracts/proof/public_proof_contract.yaml"
DEFAULT_MANUAL_BASELINE_TEMPLATE = "contracts/proof/manual_baseline.example.json"
MANUAL_BASELINE_REQUIRED_FIELDS = (
    "status",
    "reason",
    "operator",
    "captured_at",
    "duration_ms",
    "mistake_count",
    "rework_required",
)
MANUAL_BASELINE_PLACEHOLDER_VALUES = {
    "operator": {"your_name"},
}
MANUAL_BASELINE_PLACEHOLDER_SNIPPETS = {
    "reason": ("Template only.",),
    "notes": ("Replace every value with actual observations.",),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a reproducible value-proof report for the canonical benchmark pack")
    parser.add_argument("--root", default=".")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--review-threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--manual-baseline-json", default="")
    return parser.parse_args()


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid yaml payload: {path}")
    return payload


def _external_tmp_root() -> Path:
    root = Path("/tmp/fileman-value-proof")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _durable_artifact_root(repo_root: Path) -> Path:
    raw = os.environ.get("FILEMAN_ARTIFACT_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve() / "value-proof"
    return (repo_root / ".runtime-cache" / "logs" / "value-proof" / "artifacts").resolve()


def _copy_dataset(source: Path, target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for item in sorted(source.iterdir()):
        if not item.is_file():
            continue
        dst = target / item.name
        shutil.copy2(item, dst)
        copied.append(dst)
    return copied


def _run(repo_root: Path, cmd: list[str]) -> float:
    return _run_with_bundle_root(repo_root, cmd, run_bundle_root=None)


def _run_with_bundle_root(repo_root: Path, cmd: list[str], *, run_bundle_root: Path | None) -> float:
    env = os.environ.copy()
    env["FILEMAN_ALLOW_HOST_EXECUTION"] = "1"
    external_tmp = _external_tmp_root()
    env["TMPDIR"] = str(external_tmp)
    env["TMP"] = str(external_tmp)
    env["TEMP"] = str(external_tmp)
    if run_bundle_root is not None:
        run_bundle_root.mkdir(parents=True, exist_ok=True)
        env["FILEMAN_RUN_BUNDLE_ROOT"] = str(run_bundle_root)
    if not str(env.get("FILEMAN_ROLLBACK_HMAC_KEY", "")).strip():
        env["FILEMAN_ROLLBACK_HMAC_KEY"] = "value-proof-benchmark-hmac-key"
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=repo_root, env=env, text=True, capture_output=True, check=False)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")
    return duration_ms


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _copy_artifact(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def _manual_review_required(rows: list[dict[str, Any]], *, threshold: float) -> int:
    count = 0
    for row in rows:
        ai = row.get("ai")
        confidence = ai.get("confidence") if isinstance(ai, dict) else None
        if isinstance(confidence, (int, float)) and float(confidence) < threshold:
            count += 1
    return count


def _missing_manual_baseline() -> dict[str, Any]:
    return {
        "status": DEFAULT_MANUAL_BASELINE_STATUS,
        "state": "missing",
        "state_summary": (
            "No manual baseline JSON was provided, so this run only contains the system benchmark without a recorded human comparison."
        ),
        "reason": (
            "The automated harness will not fabricate human cleanup timing. "
            "Record a real manual baseline as described in docs/usage.md and docs/open_source_runbook.md "
            "before making stronger value-proof claims."
        ),
        "template": DEFAULT_MANUAL_BASELINE_TEMPLATE,
    }


def _require_non_empty_string(payload: dict[str, Any], key: str, *, path: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"manual baseline missing required field: {key} ({path})")
    normalized = value.strip()
    if normalized in MANUAL_BASELINE_PLACEHOLDER_VALUES.get(key, set()):
        raise SystemExit(f"manual baseline uses template placeholder for {key}: {path}")
    for snippet in MANUAL_BASELINE_PLACEHOLDER_SNIPPETS.get(key, ()):
        if snippet in normalized:
            raise SystemExit(f"manual baseline uses template placeholder for {key}: {path}")
    return normalized


def _load_manual_baseline(path_arg: str) -> dict[str, Any]:
    if not path_arg.strip():
        return _missing_manual_baseline()

    path = Path(path_arg).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"manual baseline must be a JSON object: {path}")
    if path == Path(DEFAULT_MANUAL_BASELINE_TEMPLATE).resolve():
        raise SystemExit(f"manual baseline rejected: template file is not a recorded baseline: {path}")
    for key in MANUAL_BASELINE_REQUIRED_FIELDS:
        if key not in payload:
            raise SystemExit(f"manual baseline missing required field: {key} ({path})")
    status = _require_non_empty_string(payload, "status", path=path)
    if status == "template":
        raise SystemExit(f"manual baseline rejected: template status is not a recorded baseline: {path}")
    if status != "recorded":
        raise SystemExit(f"manual baseline status must be recorded: {path}")
    reason = _require_non_empty_string(payload, "reason", path=path)
    operator = _require_non_empty_string(payload, "operator", path=path)
    captured_at = _require_non_empty_string(payload, "captured_at", path=path)
    duration_ms = payload.get("duration_ms")
    if not isinstance(duration_ms, (int, float)) or float(duration_ms) <= 0:
        raise SystemExit(f"manual baseline duration_ms must be > 0: {path}")
    mistake_count = payload.get("mistake_count")
    if not isinstance(mistake_count, int) or mistake_count < 0:
        raise SystemExit(f"manual baseline mistake_count must be >= 0 integer: {path}")
    rework_required = payload.get("rework_required")
    if not isinstance(rework_required, bool):
        raise SystemExit(f"manual baseline rework_required must be boolean: {path}")
    notes = payload.get("notes")
    if notes is not None:
        if not isinstance(notes, str) or not notes.strip():
            raise SystemExit(f"manual baseline notes must be a non-empty string when provided: {path}")
        for snippet in MANUAL_BASELINE_PLACEHOLDER_SNIPPETS.get("notes", ()):
            if snippet in notes.strip():
                raise SystemExit(f"manual baseline uses template placeholder for notes: {path}")

    manual_baseline = {
        "status": status,
        "state": "recorded",
        "state_summary": "A recorded human baseline passed fail-close validation and can now be read next to the system benchmark.",
        "reason": reason,
        "operator": operator,
        "captured_at": captured_at,
        "duration_ms": duration_ms,
        "mistake_count": mistake_count,
        "rework_required": rework_required,
        "source": str(path),
    }
    if notes is not None:
        manual_baseline["notes"] = notes.strip()
    return manual_baseline


def _assess_value_tiers(
    contract: dict[str, Any],
    *,
    total_files: int,
    manual_status: str,
    durable_receipts_ready: bool,
) -> tuple[str, dict[str, Any]]:
    tier_order = [str(item) for item in contract.get("tier_order", [])]
    tier_requirements = dict(contract.get("value_proof", {}).get("tier_requirements", {}))
    tiers: dict[str, Any] = {}
    attained = tier_order[0] if tier_order else "smoke"

    for tier_name in tier_order:
        requirement = dict(tier_requirements.get(tier_name, {}))
        min_dataset_files = int(requirement.get("min_dataset_files", 1))
        allowed_statuses = [str(item) for item in requirement.get("manual_baseline_statuses", [])]
        durable_required = bool(requirement.get("durable_receipts_required", False))
        gaps: list[str] = []
        if total_files < min_dataset_files:
            gaps.append(
                f"The current sample has {total_files} files, below the {min_dataset_files} files required for {tier_name}-tier claims."
            )
        if allowed_statuses and manual_status not in allowed_statuses:
            gaps.append("A recorded manual baseline is still missing, so automated results cannot be compared with human timing yet.")
        if durable_required and not durable_receipts_ready:
            gaps.append("Durable receipts are incomplete, so an external reviewer cannot follow one continuous evidence chain.")
        achieved = not gaps
        tiers[tier_name] = {
            "achieved": achieved,
            "summary": str(requirement.get("summary", "")),
            "gaps": gaps,
            "requirements": {
                "min_dataset_files": min_dataset_files,
                "manual_baseline_statuses": allowed_statuses,
                "durable_receipts_required": durable_required,
            },
        }
        if achieved:
            attained = tier_name

    return attained, tiers


def _build_proof_boundaries(
    contract: dict[str, Any],
    *,
    total_files: int,
    manual_status: str,
    attained_tier: str,
    tier_matrix: dict[str, Any],
) -> dict[str, Any]:
    public_requirement = dict(contract.get("value_proof", {}).get("tier_requirements", {}).get("public", {}))
    public_min_files = int(public_requirement.get("min_dataset_files", total_files))

    if manual_status == "recorded":
        manual_baseline_boundary = (
            "This report does not prove that the recorded human baseline can be generalized to every user "
            "or every directory shape. It only proves the human comparison for this recorded sample."
        )
    else:
        manual_baseline_boundary = (
            "This report does not prove how long a human would take on the same batch, "
            "because no recorded manual baseline has been supplied yet."
        )

    if total_files < public_min_files:
        dataset_scale_boundary = (
            f"This report does not prove public-tier sample-scale value because the canonical pack only has {total_files} files, "
            f"below the {public_min_files} files required for public-tier claims."
        )
    else:
        dataset_scale_boundary = (
            f"This report does not automatically generalize to larger or differently distributed datasets. "
            f"The canonical pack has {total_files} files, but target samples still need fresh evidence."
        )

    return {
        "proves": [
            "The analyze/apply/rollback mainline ran successfully on the fixed golden_input sample in this run.",
            "Low-confidence rows are counted separately instead of being disguised as ready for fully automatic writes.",
            "Each step leaves a durable receipt so an external reviewer can trace manifest, report, and rollback evidence.",
        ],
        "does_not_prove": [
            manual_baseline_boundary,
            dataset_scale_boundary,
            (
                "This report is not public-headline proof. Right now it only "
                f"reaches {attained_tier}-tier and should be read as a "
                "reviewable value sample."
            ),
        ],
        "remaining_gaps": list(
            dict.fromkeys(
                gap
                for tier_payload in tier_matrix.values()
                if not bool(tier_payload.get("achieved"))
                for gap in tier_payload.get("gaps", [])
            )
        ),
    }


def _build_upgrade_pack_summary(contract: dict[str, Any]) -> dict[str, Any]:
    pack = dict(contract.get("value_proof", {}).get("upgrade_pack", {}))
    copied_file = str(pack.get("copied_file_name", "manual-baseline.json"))
    manifest_name = str(pack.get("manifest_file_name", "upgrade-pack.json"))
    return {
        "pack_id": str(pack.get("pack_id", "value-proof-upgrade-pack")),
        "human_input_kind": str(pack.get("human_input_kind", "manual_baseline")),
        "template": DEFAULT_MANUAL_BASELINE_TEMPLATE,
        "prepared_file": f".runtime-cache/logs/value-proof/upgrade-pack/{copied_file}",
        "manifest_path": f".runtime-cache/logs/value-proof/upgrade-pack/{manifest_name}",
        "current_claim_tier_cap": str(pack.get("current_claim_tier_cap", "smoke")),
        "recorded_input_status_required": str(pack.get("recorded_input_status_required", "recorded")),
        "recorded_input_unlocks_tier": str(pack.get("recorded_input_unlocks_tier", "interview")),
        "still_blocked_tiers_after_recorded_input": [str(item) for item in pack.get("still_blocked_tiers_after_recorded_input", [])],
        "prepare_command": str(pack.get("prepare_command", "bash tooling/runtime/run_value_proof.sh --prepare-upgrade-pack")),
        "rerun_command_example": (
            "bash tooling/runtime/run_value_proof.sh --manual-baseline-json "
            '".runtime-cache/logs/value-proof/upgrade-pack/manual-baseline.json"'
        ),
        "fail_close": bool(pack.get("fail_close", True)),
    }


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.root).resolve()
    dataset_root = (repo_root / args.dataset).resolve()
    output_path = (repo_root / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    contract = _load_yaml(repo_root / PUBLIC_PROOF_CONTRACT)

    if not dataset_root.exists():
        raise SystemExit(f"dataset missing: {dataset_root}")

    workspace_root = Path(tempfile.mkdtemp(prefix="value-proof-", dir=_external_tmp_root()))
    input_root = workspace_root / "input"
    output_root = workspace_root / "organized"
    artifacts_root = workspace_root / "artifacts"
    run_bundle_root = workspace_root / ".fileman" / "runs"
    manifest_path = artifacts_root / "manifest.jsonl"
    analyze_report = artifacts_root / "analyze-report.json"
    applied_manifest = artifacts_root / "applied-manifest.jsonl"
    apply_report = artifacts_root / "apply-report.json"
    rollback_manifest = artifacts_root / "rollback-manifest.jsonl"
    dataset_files = _copy_dataset(dataset_root, input_root)
    output_root.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    try:
        analyze_ms = _run_with_bundle_root(
            repo_root,
            [
                "bash",
                "tooling/runtime/run_analyze.sh",
                "--input",
                str(input_root),
                "--manifest",
                str(manifest_path),
                "--report",
                str(analyze_report),
                "--offline",
                "--run-id",
                "value_proof_analyze",
                "--generator-version",
                "4.0.0",
                "--durability",
                "none",
                "--workers",
                "1",
            ],
            run_bundle_root=run_bundle_root,
        )
        apply_ms = _run_with_bundle_root(
            repo_root,
            [
                "bash",
                "tooling/runtime/run_apply.sh",
                "--manifest",
                str(manifest_path),
                "--output",
                str(output_root),
                "--input-root",
                str(input_root),
                "--verify-sha1",
                "--out-manifest",
                str(applied_manifest),
                "--report",
                str(apply_report),
                "--rollback-manifest",
                str(rollback_manifest),
                "--durability",
                "none",
            ],
            run_bundle_root=run_bundle_root,
        )
        rollback_ms = _run_with_bundle_root(
            repo_root,
            [
                "bash",
                "tooling/runtime/run_rollback.sh",
                "--manifest",
                str(rollback_manifest),
                "--allowed-root",
                f"{input_root},{output_root}",
                "--no-strict-integrity",
            ],
            run_bundle_root=run_bundle_root,
        )

        analyzed_rows = _read_jsonl(manifest_path)
        applied_rows = _read_jsonl(applied_manifest)
        analyze_payload = _read_json(analyze_report)
        apply_payload = _read_json(apply_report)
        review_required = _manual_review_required(analyzed_rows, threshold=float(args.review_threshold))
        durable_root = _durable_artifact_root(repo_root) / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        durable_root.mkdir(parents=True, exist_ok=True)
        durable_manifest = _copy_artifact(manifest_path, durable_root / "manifest.jsonl")
        durable_analyze_report = _copy_artifact(analyze_report, durable_root / "analyze-report.json")
        durable_applied_manifest = _copy_artifact(applied_manifest, durable_root / "applied-manifest.jsonl")
        durable_apply_report = _copy_artifact(apply_report, durable_root / "apply-report.json")
        durable_rollback_manifest = _copy_artifact(rollback_manifest, durable_root / "rollback-manifest.jsonl")
        durable_receipts_ready = all(
            path.exists()
            for path in (
                durable_manifest,
                durable_analyze_report,
                durable_applied_manifest,
                durable_apply_report,
                durable_rollback_manifest,
            )
        )
        manual_baseline = _load_manual_baseline(args.manual_baseline_json)
        attained_tier, tier_matrix = _assess_value_tiers(
            contract,
            total_files=len(dataset_files),
            manual_status=str(manual_baseline.get("status", DEFAULT_MANUAL_BASELINE_STATUS)),
            durable_receipts_ready=durable_receipts_ready,
        )
        proof_boundaries = _build_proof_boundaries(
            contract,
            total_files=len(dataset_files),
            manual_status=str(manual_baseline.get("status", DEFAULT_MANUAL_BASELINE_STATUS)),
            attained_tier=attained_tier,
            tier_matrix=tier_matrix,
        )

        payload = {
            "schema_version": 1,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "dataset": {
                "id": dataset_root.name,
                "source": str(dataset_root.relative_to(repo_root)),
                "total_files": len(dataset_files),
                "files": [path.name for path in dataset_files],
            },
            "review_gate": {
                "confidence_threshold": float(args.review_threshold),
                "manual_review_required_rows": review_required,
                "auto_apply_eligible_rows": max(0, len(analyzed_rows) - review_required),
            },
            "system_benchmark": {
                "analyze_offline": {
                    "duration_ms": analyze_ms,
                    "total_rows": len(analyzed_rows),
                    "report_total": analyze_payload.get("total"),
                },
                "analyze_apply_execute": {
                    "duration_ms": round(analyze_ms + apply_ms, 2),
                    "apply_duration_ms": apply_ms,
                    "applied_rows": len(applied_rows),
                    "report_total": apply_payload.get("total"),
                },
                "rollback_execute": {
                    "duration_ms": rollback_ms,
                    "rollback_rows": len(_read_jsonl(rollback_manifest)),
                    "strict_integrity": False,
                },
            },
            "manual_baseline": manual_baseline,
            "upgrade_pack": _build_upgrade_pack_summary(contract),
            "evidence_tiers": {
                "canonical_pack_tier": "smoke",
                "attained_tier_this_run": attained_tier,
                "headline_public_allowed": False,
                "tiers": tier_matrix,
            },
            "proof_boundaries": proof_boundaries,
            "newcomer_truth": {
                "first_command": "bash tooling/runtime/run_value_proof.sh",
                "docs": [
                    "docs/usage.md",
                    "docs/open_source_runbook.md",
                ],
                "human_reading_hint": (
                    "Read evidence_tiers and proof_boundaries before you read the benchmark numbers. Do not start with timing alone."
                ),
            },
            "durable_artifacts_root": str(durable_root),
            "artifacts": {
                "manifest": str(durable_manifest),
                "analyze_report": str(durable_analyze_report),
                "applied_manifest": str(durable_applied_manifest),
                "apply_report": str(durable_apply_report),
                "rollback_manifest": str(durable_rollback_manifest),
            },
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"value_proof written: {output_path}")
        return 0
    finally:
        shutil.rmtree(workspace_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
