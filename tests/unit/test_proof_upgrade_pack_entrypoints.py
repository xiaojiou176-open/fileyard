from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_run_value_proof_prepare_upgrade_pack_creates_editable_manual_baseline(tmp_path: Path) -> None:
    repo_root = _repo_root()
    target = tmp_path / "value-proof-pack"
    env = os.environ.copy()
    env["FILEYARD_ALLOW_HOST_EXECUTION"] = "1"

    proc = subprocess.run(
        ["bash", "tooling/runtime/run_value_proof.sh", "--prepare-upgrade-pack", str(target)],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    baseline = target / "manual-baseline.json"
    readme = target / "README.md"
    manifest = target / "upgrade-pack.json"
    assert baseline.exists()
    assert readme.exists()
    assert manifest.exists()
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "template"
    assert manifest_payload["pack_id"] == "value-proof-upgrade-pack"
    assert manifest_payload["human_input_kind"] == "manual_baseline"
    assert manifest_payload["current_claim_tier_cap"] == "smoke"
    assert manifest_payload["recorded_input_status_required"] == "recorded"
    assert manifest_payload["recorded_input_unlocks_tier"] == "interview"
    assert manifest_payload["still_blocked_tiers_after_recorded_input"] == ["public"]
    assert "Value Proof Upgrade Pack" in readme.read_text(encoding="utf-8")
    assert "upgrade-pack.json" in readme.read_text(encoding="utf-8")
    assert "manual-baseline.json" in proc.stdout
    assert "--manual-baseline-json" in proc.stdout


def test_ai_eval_prepare_upgrade_pack_creates_editable_human_rubric(tmp_path: Path) -> None:
    repo_root = _repo_root()
    target = tmp_path / "ai-eval-pack"
    env = os.environ.copy()
    env["FILEYARD_ALLOW_HOST_EXECUTION"] = "1"

    proc = subprocess.run(
        ["bash", "tooling/gates/ai_eval_gate.sh", "--prepare-upgrade-pack", str(target)],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    rubric = target / "human-rubric.json"
    readme = target / "README.md"
    manifest = target / "upgrade-pack.json"
    assert rubric.exists()
    assert readme.exists()
    assert manifest.exists()
    payload = json.loads(rubric.read_text(encoding="utf-8"))
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "template"
    assert manifest_payload["pack_id"] == "ai-eval-upgrade-pack"
    assert manifest_payload["human_input_kind"] == "human_rubric"
    assert manifest_payload["current_claim_tier_cap"] == "smoke"
    assert manifest_payload["recorded_input_status_required"] == "recorded"
    assert manifest_payload["recorded_input_unlocks_tier"] == "public"
    assert manifest_payload["prerequisite_before_recorded_input_unlocks"] == ["live_receipt.status == passed"]
    assert "AI Eval Upgrade Pack" in readme.read_text(encoding="utf-8")
    assert "upgrade-pack.json" in readme.read_text(encoding="utf-8")
    assert "human-rubric.json" in proc.stdout
    assert "--human-rubric-json" in proc.stdout


def test_proof_upgrade_pack_prepares_value_and_ai_upgrade_inputs(tmp_path: Path) -> None:
    repo_root = _repo_root()
    target = tmp_path / "proof-pack"
    env = os.environ.copy()
    env["FILEYARD_ALLOW_HOST_EXECUTION"] = "1"

    proc = subprocess.run(
        ["bash", "tooling/gates/proof_upgrade_pack.sh", str(target)],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    value_file = target / "value-proof" / "manual-baseline.json"
    ai_file = target / "ai-eval" / "human-rubric.json"
    root_manifest = target / "proof-upgrade-pack.json"
    assert value_file.exists()
    assert ai_file.exists()
    assert root_manifest.exists()

    value_payload = json.loads(value_file.read_text(encoding="utf-8"))
    ai_payload = json.loads(ai_file.read_text(encoding="utf-8"))
    manifest_payload = json.loads(root_manifest.read_text(encoding="utf-8"))
    assert value_payload["status"] == "template"
    assert ai_payload["status"] == "template"
    assert manifest_payload["status"] == "template_only"
    assert manifest_payload["packs"]["value_proof"]["current_claim_tier_cap"] == "smoke"
    assert manifest_payload["packs"]["ai_eval"]["current_claim_tier_cap"] == "smoke"
    assert "proof upgrade pack prepared" in proc.stdout
    assert "manual-baseline.json" in proc.stdout
    assert "human-rubric.json" in proc.stdout
