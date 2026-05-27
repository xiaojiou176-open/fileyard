#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

DEFAULT_OUTPUT = ".runtime-cache/logs/ai-eval/summary.json"
PUBLIC_PROOF_CONTRACT = "contracts/proof/public_proof_contract.yaml"
DEFAULT_HUMAN_RUBRIC_TEMPLATE = "contracts/ai/human_rubric.example.json"


@dataclass
class SuiteResult:
    suite_id: str
    mode: str
    status: str
    passed: int
    failed: int
    skipped: int
    total: int
    pass_rate: float
    details: list[dict[str, Any]]
    duration_ms: int
    metrics: dict[str, Any]
    reason: str | None = None
    artifacts: dict[str, str] | None = None
    manifest_path: str | None = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the repository AI minimum evidence pack")
    parser.add_argument("--root", default=".")
    parser.add_argument("--spec", default="contracts/ai/eval_cases.yaml")
    parser.add_argument("--baseline", default="contracts/ai/eval_baseline.yaml")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--mode", choices=("auto", "offline", "live"), default="auto")
    parser.add_argument("--human-rubric-json", default="")
    return parser.parse_args()


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid yaml payload: {path}")
    return payload


def _human_rubric_template_path(baseline: dict[str, Any]) -> str:
    template = str(baseline.get("human_rubric_template", "")).strip()
    return template or DEFAULT_HUMAN_RUBRIC_TEMPLATE


def _load_human_rubric(path_arg: str, *, template_path: str, repo_root: Path) -> dict[str, Any]:
    if not path_arg.strip():
        return {
            "status": "not_recorded",
            "reason": "当前还没有把 live 结果和人类评分表并排留档，所以不能把 AI live 质量说成 public-grade。",
            "template": template_path,
        }

    path = Path(path_arg).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"human rubric must be a JSON object: {path}")

    template_candidate = Path(template_path)
    template_file = template_candidate if template_candidate.is_absolute() else (repo_root / template_candidate)
    template_payload: dict[str, Any] | None = None
    if template_file.exists():
        template_payload_raw = json.loads(template_file.read_text(encoding="utf-8"))
        if isinstance(template_payload_raw, dict):
            template_payload = template_payload_raw
        if path == template_file.resolve():
            raise SystemExit(f"human rubric rejected: template file is not a recorded rubric: {path}")
    if template_payload is not None and payload == template_payload:
        raise SystemExit(f"human rubric rejected: template contents are not a recorded rubric: {path}")

    status = str(payload.get("status", "")).strip() or "not_recorded"
    if status == "template":
        raise SystemExit(f"human rubric rejected: template status is not a recorded rubric: {path}")
    if status != "recorded":
        raise SystemExit(f"human rubric status must be recorded: {path}")

    reviewer = str(payload.get("reviewer", "")).strip()
    if not reviewer:
        raise SystemExit(f"human rubric missing required field: reviewer: {path}")
    if reviewer in {"human_reviewer", "your_name"}:
        raise SystemExit(f"human rubric rejected: placeholder reviewer is not a recorded rubric: {path}")

    captured_at = str(payload.get("captured_at", "")).strip()
    if not captured_at:
        raise SystemExit(f"human rubric missing required field: captured_at: {path}")

    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise SystemExit(f"human rubric rows must be a non-empty list: {path}")
    allowed_statuses = {"pass", "borderline", "fail"}
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SystemExit(f"human rubric row must be an object: {path}#{idx}")
        row_name = str(row.get("row", "")).strip()
        row_status = str(row.get("status", "")).strip()
        if not row_name:
            raise SystemExit(f"human rubric missing row name: {path}#{idx}")
        if row_name == "example-row":
            raise SystemExit(f"human rubric rejected: placeholder row is not a recorded rubric: {path}#{idx}")
        if row_status not in allowed_statuses:
            raise SystemExit(f"human rubric row status must be one of pass/borderline/fail: {path}#{idx}")
        row_notes = str(row.get("notes", "")).strip().lower()
        if "replace this example" in row_notes:
            raise SystemExit(f"human rubric rejected: placeholder row notes are not a recorded rubric: {path}#{idx}")

    notes = str(payload.get("notes", "")).strip()
    if "replace this example" in notes.lower():
        raise SystemExit(f"human rubric rejected: placeholder notes are not a recorded rubric: {path}")

    agreement_rate = payload.get("agreement_rate")
    if agreement_rate is not None:
        try:
            numeric_rate = float(agreement_rate)
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"human rubric agreement_rate must be numeric: {path}") from exc
        if not 0.0 <= numeric_rate <= 1.0:
            raise SystemExit(f"human rubric agreement_rate must be between 0 and 1: {path}")

    human_rubric = {
        "status": status,
        "reason": str(payload.get("reason", "已记录人类 rubric 复核。")),
        "source": str(path),
        "template": template_path,
        "rows_count": len(rows),
    }
    for key in ("reviewer", "captured_at", "notes", "agreement_rate"):
        if key in payload:
            human_rubric[key] = payload[key]
    return human_rubric


def _collect_suite_status_map(suite_results: list["SuiteResult"]) -> dict[str, str]:
    return {result.suite_id: result.status for result in suite_results}


def _assess_ai_eval_tiers(
    contract: dict[str, Any],
    suite_results: list["SuiteResult"],
    *,
    human_rubric_status: str,
) -> tuple[str, dict[str, Any]]:
    tier_order = [str(item) for item in contract.get("tier_order", [])]
    ai_eval_contract = dict(contract.get("ai_eval", {}))
    tier_requirements = dict(ai_eval_contract.get("tier_requirements", {}))
    suite_statuses = _collect_suite_status_map(suite_results)
    live_suite_id = str(ai_eval_contract.get("live_suite_id", "live-rubric"))
    live_status = suite_statuses.get(live_suite_id, "missing")
    tiers: dict[str, Any] = {}
    attained = tier_order[0] if tier_order else "smoke"

    for tier_name in tier_order:
        requirement = dict(tier_requirements.get(tier_name, {}))
        required_offline = [str(item) for item in requirement.get("required_offline_suites", [])]
        live_required = bool(requirement.get("live_receipt_required", False))
        allowed_human_statuses = [str(item) for item in requirement.get("human_rubric_statuses", [])]
        gaps: list[str] = []
        for suite_id in required_offline:
            if suite_statuses.get(suite_id) != "passed":
                gaps.append(f"离线 suite {suite_id} 没有通过，连最基本的 deterministic 质量都还不能算稳。")
        if live_required and live_status != "passed":
            gaps.append("还没有 fresh live receipt，所以不能把 AI 结果说成已被真实 Gemini 持续证明。")
        if allowed_human_statuses and human_rubric_status not in allowed_human_statuses:
            gaps.append("还没有人类 rubric 基线，外部人看不到模型结果和人工判断是否一致。")
        achieved = not gaps
        tiers[tier_name] = {
            "achieved": achieved,
            "summary": str(requirement.get("summary", "")),
            "gaps": gaps,
            "requirements": {
                "required_offline_suites": required_offline,
                "live_receipt_required": live_required,
                "human_rubric_statuses": allowed_human_statuses,
            },
        }
        if achieved:
            attained = tier_name

    return attained, tiers


def _tier_index(tier_order: list[str], tier_name: str) -> int:
    try:
        return tier_order.index(tier_name)
    except ValueError:
        return -1


def _blocked_tier_gaps(
    tier_order: list[str],
    attained_tier: str,
    tier_matrix: dict[str, Any],
) -> list[str]:
    attained_index = _tier_index(tier_order, attained_tier)
    gaps: list[str] = []
    for tier_name in tier_order:
        if _tier_index(tier_order, tier_name) <= attained_index:
            continue
        tier_payload = dict(tier_matrix.get(tier_name, {}))
        for gap in tier_payload.get("gaps", []):
            if gap not in gaps:
                gaps.append(str(gap))
    return gaps


def _build_live_receipt_summary(
    live_suite_id: str,
    live_suite: SuiteResult | None,
) -> dict[str, Any]:
    if live_suite is None:
        return {
            "suite_id": live_suite_id,
            "status": "missing",
            "reason": "live suite missing",
            "gate": "suite_missing",
            "claim_cap": "smoke",
            "honest_statement": "这次 summary 里连 live suite 都不存在，所以不能把结果说成拿到了 fresh live receipt。",
        }

    gate = "passed"
    claim_cap = "interview"
    honest_statement = "这次拿到了 fresh live receipt，但要不要讲到 public-tier 还要继续看 human rubric。"
    if live_suite.status == "failed":
        gate = "live_failed"
        claim_cap = "smoke"
        honest_statement = "这次 live suite 自己就没过，所以不能把 AI 质量说成已经通过 live 验证。"
    elif live_suite.status == "skipped":
        claim_cap = "smoke"
        if live_suite.reason == "missing credentials":
            gate = "credentials_missing"
            honest_statement = "这次没有凭证，所以 live suite 根本没执行；当前结果最多只能诚实讲到 smoke-tier。"
        elif live_suite.reason == "offline mode":
            gate = "run_mode_offline"
            honest_statement = "这次明确跑的是 offline mode，live suite 没执行；当前结果最多只能诚实讲到 smoke-tier。"
        else:
            gate = "skipped"
            honest_statement = "这次 live suite 被跳过了，所以不能把结果说成已经拿到 fresh live receipt。"

    return {
        "suite_id": live_suite_id,
        "status": live_suite.status,
        "reason": live_suite.reason,
        "gate": gate,
        "claim_cap": claim_cap,
        "honest_statement": honest_statement,
    }


def _build_human_rubric_summary(human_rubric: dict[str, Any]) -> dict[str, Any]:
    status = str(human_rubric.get("status", "not_recorded")).strip() or "not_recorded"
    gate = "recorded" if status == "recorded" else "missing"
    claim_cap = "public" if status == "recorded" else "interview"
    honest_statement = (
        "这次已经把人类 rubric 留档了，可以和 live receipt 一起讨论 public-tier 边界。"
        if status == "recorded"
        else "这次还没有人类 rubric 留档，所以就算 live 通过，也不能把结果讲成 public-tier。"
    )
    return {
        **human_rubric,
        "status": status,
        "gate": gate,
        "claim_cap": claim_cap,
        "honest_statement": honest_statement,
    }


def _build_claim_readiness(
    tier_order: list[str],
    attained_tier: str,
    tier_matrix: dict[str, Any],
) -> dict[str, Any]:
    blocked_tiers = [tier_name for tier_name in tier_order if _tier_index(tier_order, tier_name) > _tier_index(tier_order, attained_tier)]
    status_map = {
        "smoke": "smoke_only",
        "interview": "interview_ready",
        "public": "public_ready",
    }
    why_not_higher = _blocked_tier_gaps(tier_order, attained_tier, tier_matrix)
    honest_statement_map = {
        "smoke": "当前只拿到了 smoke-tier 证据，不能把 feature 已存在误讲成 interview/public-tier 证明。",
        "interview": "当前已经有 interview-tier 证据，但还缺 public-tier 所需的人类 rubric 或同等级边界材料。",
        "public": "当前这次运行达到了 public-tier 所需的最小仓内证据，但仍不等于长期线上效果证明。",
    }
    return {
        "status": status_map.get(attained_tier, "smoke_only"),
        "max_safe_claim_tier": attained_tier,
        "blocked_tiers": blocked_tiers,
        "why_not_higher": why_not_higher,
        "fail_close": True,
        "honest_statement": honest_statement_map.get(
            attained_tier,
            "当前 summary 会按更保守的 tier 解释结果，避免把缺失证据说成已经具备。",
        ),
    }


def _build_upgrade_pack_summary(proof_contract: dict[str, Any]) -> dict[str, Any]:
    pack = dict(proof_contract.get("ai_eval", {}).get("upgrade_pack", {}))
    copied_file = str(pack.get("copied_file_name", "human-rubric.json"))
    manifest_name = str(pack.get("manifest_file_name", "upgrade-pack.json"))
    return {
        "pack_id": str(pack.get("pack_id", "ai-eval-upgrade-pack")),
        "human_input_kind": str(pack.get("human_input_kind", "human_rubric")),
        "template": DEFAULT_HUMAN_RUBRIC_TEMPLATE,
        "prepared_file": f".runtime-cache/logs/ai-eval/upgrade-pack/{copied_file}",
        "manifest_path": f".runtime-cache/logs/ai-eval/upgrade-pack/{manifest_name}",
        "current_claim_tier_cap": str(pack.get("current_claim_tier_cap", "smoke")),
        "recorded_input_status_required": str(pack.get("recorded_input_status_required", "recorded")),
        "recorded_input_unlocks_tier": str(pack.get("recorded_input_unlocks_tier", "public")),
        "prerequisite_before_recorded_input_unlocks": [str(item) for item in pack.get("prerequisite_before_recorded_input_unlocks", [])],
        "prepare_command": str(pack.get("prepare_command", "bash tooling/gates/ai_eval_gate.sh --prepare-upgrade-pack")),
        "rerun_command_example": (
            'bash tooling/gates/ai_eval_gate.sh --human-rubric-json ".runtime-cache/logs/ai-eval/upgrade-pack/human-rubric.json"'
        ),
        "fail_close": bool(pack.get("fail_close", True)),
    }


def _external_tmp_root() -> Path:
    root = Path("/tmp/fileorganize-ai-eval")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _durable_artifact_root(repo_root: Path) -> Path:
    raw = os.environ.get("FILEORGANIZE_ARTIFACT_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve() / "ai-eval"
    return (repo_root / ".runtime-cache" / "logs" / "ai-eval" / "artifacts").resolve()


def _read_manifest(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row_path = Path(str(row["path"])).name
        rows[row_path] = row
    return rows


def _normalize_manifest_rows(rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for row_name, row in rows.items():
        cloned = json.loads(json.dumps(row, ensure_ascii=False))
        if "path" in cloned:
            cloned["path"] = Path(str(cloned["path"])).name
        if "input_root" in cloned:
            cloned["input_root"] = "<INPUT_ROOT>"
        if "file_mtime" in cloned:
            cloned["file_mtime"] = "<FILE_MTIME>"
        if "mime" in cloned:
            cloned["mime"] = "<MIME>"
        if "run_id" in cloned:
            cloned["run_id"] = "<RUN_ID>"
        normalized[row_name] = cloned
    return normalized


def _get_field(row: dict[str, Any], field: str) -> Any:
    current: Any = row
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _suite_metrics(rows: dict[str, dict[str, Any]], *, confidence_threshold: float) -> dict[str, Any]:
    low_confidence_rows = 0
    rows_with_confidence = 0
    for row in rows.values():
        confidence = _get_field(row, "ai.confidence")
        if isinstance(confidence, (int, float)):
            rows_with_confidence += 1
            if float(confidence) < confidence_threshold:
                low_confidence_rows += 1
    return {
        "row_count": len(rows),
        "rows_with_confidence": rows_with_confidence,
        "review_confidence_threshold": confidence_threshold,
        "manual_review_required_rows": low_confidence_rows,
        "auto_apply_eligible_rows": max(0, len(rows) - low_confidence_rows),
    }


def _case_pass(case: dict[str, Any], rows: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    row_name = str(case["row"])
    row = rows.get(row_name)
    if row is None:
        return False, f"row missing: {row_name}"
    field = str(case["field"])
    actual = _get_field(row, field)
    kind = str(case["kind"])

    if kind == "equals":
        expected = case.get("expected")
        return actual == expected, f"expected={expected!r} actual={actual!r}"
    if kind == "in_set":
        expected = list(case.get("expected", []))
        return actual in expected, f"expected_one_of={expected!r} actual={actual!r}"
    if kind == "nonempty":
        if isinstance(actual, str):
            passed = bool(actual.strip())
        elif isinstance(actual, (list, dict)):
            passed = bool(actual)
        else:
            passed = actual is not None
        return passed, f"actual={actual!r}"
    if kind == "range":
        try:
            numeric = float(actual)
        except (TypeError, ValueError):
            return False, f"not numeric: {actual!r}"
        lower = float(case["min"])
        upper = float(case["max"])
        return lower <= numeric <= upper, f"expected_range=[{lower}, {upper}] actual={numeric}"
    if kind == "exists":
        return actual is not None, f"actual={actual!r}"

    raise SystemExit(f"unsupported eval case kind: {kind}")


def _run_analyze(
    repo_root: Path,
    input_dir: Path,
    *,
    offline: bool,
    run_id: str,
    run_bundle_root: Path,
) -> Path:
    manifest_dir = Path(tempfile.mkdtemp(prefix=f"{run_id}-manifest-", dir=_external_tmp_root()))
    manifest_path = manifest_dir / "manifest.jsonl"
    report_path = manifest_dir / "report.json"
    cmd = [
        "bash",
        "tooling/runtime/run_analyze.sh",
        "--input",
        str(input_dir),
        "--manifest",
        str(manifest_path),
        "--run-id",
        run_id,
        "--generator-version",
        "4.0.0",
        "--durability",
        "none",
        "--workers",
        "1",
        "--report",
        str(report_path),
    ]
    if offline:
        cmd.append("--offline")

    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = "1"
    external_tmp = _external_tmp_root()
    env["TMPDIR"] = str(external_tmp)
    env["TMP"] = str(external_tmp)
    env["TEMP"] = str(external_tmp)
    run_bundle_root.mkdir(parents=True, exist_ok=True)
    env["FILEORGANIZE_RUN_BUNDLE_ROOT"] = str(run_bundle_root)
    proc = subprocess.run(cmd, cwd=repo_root, text=True, capture_output=True, check=False, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"analyze failed for {run_id}: {proc.stdout}\n{proc.stderr}")
    return manifest_path


def _write_sine_wave(path: Path, *, duration_seconds: float, frequency_hz: float) -> None:
    sample_rate = 16000
    total_frames = max(1, int(sample_rate * duration_seconds))
    amplitude = 14000
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(total_frames):
            value = int(amplitude * math.sin(2.0 * math.pi * frequency_hz * (index / sample_rate)))
            frames.extend(struct.pack("<h", value))
        handle.writeframes(bytes(frames))


def _prepare_suite_input(repo_root: Path, suite: dict[str, Any], tmp_root: Path) -> Path:
    input_dir = tmp_root / str(suite["id"])
    input_dir.mkdir(parents=True, exist_ok=True)
    if "input_dir" in suite:
        source = repo_root / str(suite["input_dir"])
        for item in sorted(source.iterdir()):
            if item.is_file():
                shutil.copy2(item, input_dir / item.name)
    if "synthetic_audio" in suite:
        audio = dict(suite["synthetic_audio"])
        _write_sine_wave(
            input_dir / str(audio["filename"]),
            duration_seconds=float(audio.get("duration_seconds", 0.25)),
            frequency_hz=float(audio.get("frequency_hz", 440.0)),
        )
    return input_dir


def _copy_artifact(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def _run_suite(repo_root: Path, suite: dict[str, Any], baseline: dict[str, Any], mode: str, tmp_root: Path) -> SuiteResult:
    suite_id = str(suite["id"])
    suite_mode = str(suite["mode"])
    suite_baseline = dict(baseline.get("suites", {}).get(suite_id, {}))
    case_total = len(suite.get("cases", []))
    confidence_threshold = float(baseline.get("review_confidence_threshold", 0.6))
    suite_started_at = time.perf_counter()

    if mode == "offline" and suite_mode == "live":
        return SuiteResult(
            suite_id,
            suite_mode,
            "skipped",
            0,
            0,
            case_total,
            case_total,
            0.0,
            [],
            0,
            {
                "row_count": 0,
                "rows_with_confidence": 0,
                "review_confidence_threshold": confidence_threshold,
                "manual_review_required_rows": 0,
                "auto_apply_eligible_rows": 0,
            },
            reason="offline mode",
            artifacts={},
            manifest_path=None,
        )
    if suite_mode == "live" and mode == "auto":
        if not os.getenv("GEMINI_API_KEY", "").strip() or not os.getenv("GEMINI_MODEL", "").strip():
            if bool(suite_baseline.get("allow_skip_without_credentials", False)):
                return SuiteResult(
                    suite_id,
                    suite_mode,
                    "skipped",
                    0,
                    0,
                    case_total,
                    case_total,
                    0.0,
                    [],
                    0,
                    {
                        "row_count": 0,
                        "rows_with_confidence": 0,
                        "review_confidence_threshold": confidence_threshold,
                        "manual_review_required_rows": 0,
                        "auto_apply_eligible_rows": 0,
                    },
                    reason="missing credentials",
                    artifacts={},
                    manifest_path=None,
                )
            raise SystemExit(f"live suite requires credentials: {suite_id}")
    if suite_mode == "live" and mode == "live":
        if not os.getenv("GEMINI_API_KEY", "").strip() or not os.getenv("GEMINI_MODEL", "").strip():
            raise SystemExit(f"live mode requires GEMINI_API_KEY and GEMINI_MODEL for suite: {suite_id}")

    input_dir = _prepare_suite_input(repo_root, suite, tmp_root)
    manifest_path = _run_analyze(
        repo_root,
        input_dir,
        offline=(suite_mode == "offline"),
        run_id=f"ai_eval_{suite_id}",
        run_bundle_root=tmp_root / ".fileorganize" / "runs",
    )
    rows = _read_manifest(manifest_path)

    if "expected_manifest" in suite:
        expected_rows = _normalize_manifest_rows(_read_manifest(repo_root / str(suite["expected_manifest"])))
        actual_rows = _normalize_manifest_rows(rows)
        if actual_rows != expected_rows:
            raise SystemExit(f"expected manifest mismatch for suite {suite_id}")

    details: list[dict[str, Any]] = []
    passed = failed = 0
    for case in suite.get("cases", []):
        ok, message = _case_pass(dict(case), rows)
        details.append({"id": case["id"], "status": "passed" if ok else "failed", "detail": message})
        if ok:
            passed += 1
        else:
            failed += 1

    total = passed + failed
    pass_rate = round((passed / total) if total else 1.0, 4)
    min_pass_rate = float(suite_baseline.get("min_pass_rate", 1.0))
    status = "passed" if pass_rate >= min_pass_rate else "failed"
    duration_ms = int((time.perf_counter() - suite_started_at) * 1000)
    return SuiteResult(
        suite_id=suite_id,
        mode=suite_mode,
        status=status,
        passed=passed,
        failed=failed,
        skipped=0,
        total=total,
        pass_rate=pass_rate,
        details=details,
        duration_ms=duration_ms,
        metrics=_suite_metrics(rows, confidence_threshold=confidence_threshold),
        reason=None,
        artifacts={},
        manifest_path=str(manifest_path),
    )


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.root).resolve()
    spec = _load_yaml(repo_root / args.spec)
    baseline = _load_yaml(repo_root / args.baseline)
    proof_contract = _load_yaml(repo_root / PUBLIC_PROOF_CONTRACT)
    output = repo_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    durable_root = _durable_artifact_root(repo_root) / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    durable_root.mkdir(parents=True, exist_ok=True)

    tmp_root = Path(tempfile.mkdtemp(prefix="ai-eval-", dir=_external_tmp_root()))
    try:
        suite_results = [_run_suite(repo_root, dict(suite), baseline, args.mode, tmp_root) for suite in spec.get("suites", [])]
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    for result in suite_results:
        if result.status == "skipped" or not result.manifest_path:
            continue
        manifest_src = Path(result.manifest_path)
        if not manifest_src.exists():
            continue
        suite_root = durable_root / result.suite_id
        durable_manifest = _copy_artifact(manifest_src, suite_root / "manifest.jsonl")
        result.artifacts = {
            "manifest": str(durable_manifest),
        }

    has_failed = any(result.status == "failed" for result in suite_results)
    overall_status = "failed" if has_failed else "passed"
    confidence_threshold = float(baseline.get("review_confidence_threshold", 0.6))
    total_rows = sum(int(result.metrics.get("row_count", 0)) for result in suite_results)
    manual_review_required_rows = sum(int(result.metrics.get("manual_review_required_rows", 0)) for result in suite_results)
    auto_apply_eligible_rows = sum(int(result.metrics.get("auto_apply_eligible_rows", 0)) for result in suite_results)
    human_rubric = _load_human_rubric(
        args.human_rubric_json,
        template_path=_human_rubric_template_path(baseline),
        repo_root=repo_root,
    )
    human_rubric_summary = _build_human_rubric_summary(human_rubric)
    tier_order = [str(item) for item in proof_contract.get("tier_order", [])]
    attained_tier, tier_matrix = _assess_ai_eval_tiers(
        proof_contract,
        suite_results,
        human_rubric_status=str(human_rubric_summary.get("status", "not_recorded")),
    )
    live_suite_id = str(dict(proof_contract.get("ai_eval", {})).get("live_suite_id", "live-rubric"))
    live_suite = next((result for result in suite_results if result.suite_id == live_suite_id), None)
    live_receipt_summary = _build_live_receipt_summary(live_suite_id, live_suite)
    gemini_called = bool(live_suite is not None and live_suite.status not in {"skipped", "missing"})
    proof_boundaries = {
        "proves": [
            "offline-golden 和 offline-audio-contract 这次都过了，说明离线合同仍稳定。",
            "review_gate 会把低置信度结果显式数出来，不会把 AI 输出直接包装成可无脑自动写盘。",
        ],
        "does_not_prove": [
            "这份结果不等于 AI 已被持续 live 证明；没有 fresh live receipt 时，只能说明 offline path 稳定。",
            "这份结果不等于人类评审已经和模型对齐；没有 human rubric 基线时，还不能讲 public-grade 质量。",
        ],
        "remaining_gaps": _blocked_tier_gaps(tier_order, attained_tier, tier_matrix),
    }
    claim_readiness = _build_claim_readiness(tier_order, attained_tier, tier_matrix)
    privacy_truth = {
        "gemini_called_in_this_run": gemini_called,
        "credentials_present": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "credential_values_stored": False,
        "which_steps_send_data_to_gemini": [
            "只有 live-rubric 真正执行时，suite 输入文件内容才会被送到 Gemini 做 analyze。",
        ],
        "which_steps_stay_local": [
            "offline-golden",
            "offline-audio-contract",
            "proof gate 汇总",
            "summary.json 写盘",
        ],
        "this_run_statement": (
            "本次运行没有向 Gemini 发送新样本内容。"
            if not gemini_called
            else "本次运行执行了 live-rubric，suite 输入文件内容已发送给 Gemini。"
        ),
        "receipt_statement": "证据只记录 suite 结果、durable artifact 路径和状态，不会把 API Key 写进证据。",
    }
    summary = {
        "schema_version": 1,
        "mode": args.mode,
        "overall_status": overall_status,
        "suite_count": len(suite_results),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "runtime": {
            "model": os.getenv("GEMINI_MODEL", "").strip() or None,
            "credentials_present": bool(os.getenv("GEMINI_API_KEY", "").strip()),
            "review_confidence_threshold": confidence_threshold,
        },
        "durable_artifacts_root": str(durable_root),
        "review_gate": {
            "review_confidence_threshold": confidence_threshold,
            "total_rows": total_rows,
            "manual_review_required_rows": manual_review_required_rows,
            "auto_apply_eligible_rows": auto_apply_eligible_rows,
        },
        "live_receipt": live_receipt_summary,
        "human_rubric": human_rubric_summary,
        "upgrade_pack": _build_upgrade_pack_summary(proof_contract),
        "evidence_tiers": {
            "canonical_pack_tier": "smoke",
            "attained_tier_this_run": attained_tier,
            "tiers": tier_matrix,
        },
        "claim_readiness": claim_readiness,
        "proof_boundaries": proof_boundaries,
        "privacy_truth": privacy_truth,
        "newcomer_truth": {
            "first_command": "bash tooling/gates/ai_eval_gate.sh --mode offline",
            "docs": [
                "docs/usage.md",
                "docs/open_source_runbook.md",
            ],
            "human_reading_hint": "先看 live_receipt 和 evidence_tiers，再看 suites 明细；否则很容易把 feature 存在误读成 live 已被证明。",
        },
        "suites": [
            {
                "id": result.suite_id,
                "mode": result.mode,
                "status": result.status,
                "passed": result.passed,
                "failed": result.failed,
                "skipped": result.skipped,
                "total": result.total,
                "pass_rate": result.pass_rate,
                "duration_ms": result.duration_ms,
                "reason": result.reason,
                "metrics": result.metrics,
                "details": result.details,
                "artifacts": result.artifacts or {},
            }
            for result in suite_results
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"ai_eval overall_status={overall_status}")
    for result in suite_results:
        detail = f"{result.passed}/{result.total}"
        if result.status == "skipped" and result.reason:
            detail = result.reason
        print(f"- {result.suite_id}: {result.status} ({detail})")

    return 1 if has_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
