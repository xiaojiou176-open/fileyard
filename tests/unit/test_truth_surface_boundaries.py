from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_readme_keeps_terminal_truth_and_supporting_surfaces_separate() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "delivery-complete receipt" in readme
    assert "treat repository docs as guidance rather than a live platform dashboard" in readme.lower()


def test_open_source_runbook_keeps_public_boundary_separate_from_product_value_maturity() -> None:
    runbook = (REPO_ROOT / "docs" / "open_source_runbook.md").read_text(encoding="utf-8")

    assert "Public / release / platform readiness is not the same thing as product-value maturity." in runbook
    assert "Repository docs are not a live platform dashboard." in runbook


def test_verify_repo_final_script_keeps_governance_scorecard_separate_from_delivery_truth() -> None:
    script = (REPO_ROOT / "tooling" / "gates" / "verify_repo_final.sh").read_text(encoding="utf-8")

    assert "repo-side governance scorecard only" in script
    assert "quality_gate.sh for delivery-complete truth" in script
    assert "--allow-missing-gate platform-alignment" in script
    assert '".runtime-cache/logs/quality-gate/host-summary.json"' in script
