from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_package_json_exposes_proof_upgrade_pack_entrypoint() -> None:
    package_json = (_repo_root() / "package.json").read_text(encoding="utf-8")
    assert '"proof:upgrade-pack": "bash tooling/gates/proof_upgrade_pack.sh"' in package_json


def test_proof_upgrade_pack_script_prepares_both_files(tmp_path: Path) -> None:
    repo_root = _repo_root()
    value_dir = tmp_path / "value-pack"
    ai_dir = tmp_path / "ai-pack"
    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = "1"

    proc = subprocess.run(
        ["bash", "tooling/gates/proof_upgrade_pack.sh", str(value_dir), str(ai_dir)],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    baseline = value_dir / "manual-baseline.json"
    rubric = ai_dir / "human-rubric.json"
    upgrade_manifest = tmp_path / "proof-upgrade-pack.json"
    assert baseline.exists()
    assert rubric.exists()
    assert upgrade_manifest.exists()
    assert json.loads(baseline.read_text(encoding="utf-8"))["status"] == "template"
    assert json.loads(rubric.read_text(encoding="utf-8"))["status"] == "template"
    assert json.loads(upgrade_manifest.read_text(encoding="utf-8"))["status"] == "template_only"
    assert "proof-upgrade-pack ready" in proc.stdout


def test_proof_upgrade_pack_script_also_refreshes_canonical_paths(tmp_path: Path) -> None:
    repo_root = _repo_root()
    target = tmp_path / "proof-pack"
    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = "1"

    proc = subprocess.run(
        ["bash", "tooling/gates/proof_upgrade_pack.sh", str(target)],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    canonical_value = repo_root / ".runtime-cache/logs/value-proof/upgrade-pack/manual-baseline.json"
    canonical_ai = repo_root / ".runtime-cache/logs/ai-eval/upgrade-pack/human-rubric.json"
    canonical_value_manifest = repo_root / ".runtime-cache/logs/value-proof/upgrade-pack/upgrade-pack.json"
    canonical_ai_manifest = repo_root / ".runtime-cache/logs/ai-eval/upgrade-pack/upgrade-pack.json"
    assert canonical_value.exists()
    assert canonical_ai.exists()
    assert canonical_value_manifest.exists()
    assert canonical_ai_manifest.exists()
    assert json.loads(canonical_value.read_text(encoding="utf-8"))["status"] == "template"
    assert json.loads(canonical_ai.read_text(encoding="utf-8"))["status"] == "template"
    assert json.loads(canonical_value_manifest.read_text(encoding="utf-8"))["recorded_input_unlocks_tier"] == "interview"
    assert json.loads(canonical_ai_manifest.read_text(encoding="utf-8"))["recorded_input_unlocks_tier"] == "public"
    assert "canonical value proof baseline" in proc.stdout
    assert "canonical ai eval rubric" in proc.stdout
