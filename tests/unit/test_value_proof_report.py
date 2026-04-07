from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tooling.scripts import generate_value_proof_report


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_generator(tmp_path: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    repo_root = _repo_root()
    output = tmp_path / "value-proof.json"
    env = os.environ.copy()
    env["MOVI_ALLOW_HOST_EXECUTION"] = "1"

    return subprocess.run(
        [
            sys.executable,
            str(repo_root / "tooling" / "scripts" / "generate_value_proof_report.py"),
            "--root",
            str(repo_root),
            "--output",
            str(output),
            *extra_args,
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _poison_run_bundle_root(base: Path, run_id: str) -> Path:
    summary_path = base / run_id / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("", encoding="utf-8")
    return base


def test_value_proof_report_generator_writes_expected_sections(tmp_path: Path) -> None:
    output = tmp_path / "value-proof.json"
    proc = _run_generator(tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["dataset"]["id"] == "golden_input"
    assert payload["system_benchmark"]["analyze_offline"]["total_rows"] == 10
    assert payload["review_gate"]["confidence_threshold"] == 0.6
    assert payload["manual_baseline"]["status"] == "manual_capture_required"
    assert payload["manual_baseline"]["state"] == "missing"
    assert payload["manual_baseline"]["template"] == "contracts/proof/manual_baseline.example.json"
    assert payload["upgrade_pack"]["pack_id"] == "value-proof-upgrade-pack"
    assert payload["upgrade_pack"]["current_claim_tier_cap"] == "smoke"
    assert payload["upgrade_pack"]["recorded_input_status_required"] == "recorded"
    assert payload["upgrade_pack"]["recorded_input_unlocks_tier"] == "interview"
    assert payload["upgrade_pack"]["still_blocked_tiers_after_recorded_input"] == ["public"]
    assert payload["evidence_tiers"]["canonical_pack_tier"] == "smoke"
    assert payload["evidence_tiers"]["attained_tier_this_run"] == "smoke"
    assert payload["evidence_tiers"]["headline_public_allowed"] is False
    does_not_prove = payload["proof_boundaries"]["does_not_prove"]
    total_files = payload["dataset"]["total_files"]
    public_min_files = payload["evidence_tiers"]["tiers"]["public"]["requirements"]["min_dataset_files"]

    assert does_not_prove
    assert any(f"{total_files} files" in item and f"{public_min_files} files" in item for item in does_not_prove)
    assert not any("3 files" in item for item in does_not_prove)
    assert any("manual baseline" in gap.lower() for gap in payload["proof_boundaries"]["remaining_gaps"])
    assert "durable_artifacts_root" in payload
    durable_root = Path(payload["durable_artifacts_root"]).resolve()
    assert durable_root.exists()
    for artifact_path in payload["artifacts"].values():
        assert Path(artifact_path).resolve().is_relative_to(durable_root)


def test_value_proof_report_rejects_template_manual_baseline(tmp_path: Path) -> None:
    repo_root = _repo_root()
    proc = _run_generator(
        tmp_path,
        "--manual-baseline-json",
        str(repo_root / "contracts" / "proof" / "manual_baseline.example.json"),
    )

    assert proc.returncode != 0
    assert "template" in proc.stderr
    assert "recorded baseline" in proc.stderr


@pytest.mark.parametrize(
    ("manual_payload", "expected_fragment"),
    [
        (
            {
                "status": "recorded",
                "reason": "真人已按同一批样本补录基线。",
                "operator": "terry",
                "captured_at": "2026-03-18T19:00:00-07:00",
                "duration_ms": 0,
                "mistake_count": 1,
                "rework_required": False,
            },
            "duration_ms must be > 0",
        ),
        (
            {
                "status": "recorded",
                "reason": "真人已按同一批样本补录基线。",
                "captured_at": "2026-03-18T19:00:00-07:00",
                "duration_ms": 12345,
                "mistake_count": 1,
                "rework_required": False,
            },
            "missing required field: operator",
        ),
    ],
)
def test_value_proof_report_rejects_invalid_recorded_manual_baseline(
    tmp_path: Path,
    manual_payload: dict[str, object],
    expected_fragment: str,
) -> None:
    manual_baseline = tmp_path / "invalid-manual-baseline.json"
    manual_baseline.write_text(json.dumps(manual_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    proc = _run_generator(tmp_path, "--manual-baseline-json", str(manual_baseline))

    assert proc.returncode != 0
    assert expected_fragment in proc.stderr


def test_value_proof_report_accepts_recorded_manual_baseline(tmp_path: Path) -> None:
    output = tmp_path / "value-proof.json"
    manual_baseline = tmp_path / "manual-baseline.json"
    manual_baseline.write_text(
        json.dumps(
            {
                "status": "recorded",
                "reason": "真人已按同一批样本补录基线。",
                "operator": "terry",
                "captured_at": "2026-03-18T19:00:00-07:00",
                "duration_ms": 12345,
                "mistake_count": 1,
                "rework_required": False,
                "notes": "used canonical pack",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    proc = _run_generator(tmp_path, "--manual-baseline-json", str(manual_baseline))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["manual_baseline"]["status"] == "recorded"
    assert payload["manual_baseline"]["state"] == "recorded"
    assert payload["manual_baseline"]["source"] == str(manual_baseline.resolve())
    assert payload["manual_baseline"]["duration_ms"] == 12345
    assert payload["upgrade_pack"]["recorded_input_unlocks_tier"] == "interview"
    assert payload["evidence_tiers"]["attained_tier_this_run"] == "interview"


def test_value_proof_runtime_sets_run_bundle_root_for_subprocess(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd, cwd, env, text, capture_output, check):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(generate_value_proof_report.subprocess, "run", fake_run)

    generate_value_proof_report._run_with_bundle_root(
        _repo_root(),
        ["python3", "-c", "print('ok')"],
        run_bundle_root=tmp_path / ".movi" / "runs",
    )

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["MOVI_RUN_BUNDLE_ROOT"] == str((tmp_path / ".movi" / "runs").resolve())


def test_value_proof_report_uses_isolated_run_bundle_root(tmp_path: Path) -> None:
    repo_root = _repo_root()
    output = tmp_path / "value-proof.json"
    poisoned_root = _poison_run_bundle_root(tmp_path / "poisoned-runs", "value_proof_analyze")
    env = os.environ.copy()
    env["MOVI_ALLOW_HOST_EXECUTION"] = "1"
    env["MOVI_RUN_BUNDLE_ROOT"] = str(poisoned_root)

    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tooling" / "scripts" / "generate_value_proof_report.py"),
            "--root",
            str(repo_root),
            "--output",
            str(output),
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["system_benchmark"]["analyze_offline"]["total_rows"] == 10
    assert (poisoned_root / "value_proof_analyze" / "summary.json").read_text(encoding="utf-8") == ""
