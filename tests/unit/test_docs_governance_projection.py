from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(rel_path: str) -> dict:
    payload = yaml.safe_load((REPO_ROOT / rel_path).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_docs_render_manifest_registers_governance_projection_outputs() -> None:
    manifest = _load_yaml("contracts/docs/docs_render_manifest.yaml")
    renders = {str(item["id"]): item for item in manifest.get("renders", [])}

    assert "governance-truth-reference" in renders
    assert renders["governance-truth-reference"]["output_path"] == "docs/reference/governance_truth.generated.md"
    assert "script-readme-governance-truth" in renders
    assert "architecture-governance-truth" in renders
    assert "open-source-platform-truth" in renders
    assert "runner-contract-governance-truth" in renders


def test_docs_nav_registry_tracks_generated_governance_reference_and_human_doc_guards() -> None:
    registry = _load_yaml("contracts/docs/docs_nav_registry.yaml")
    docs = {str(item["path"]): item for item in registry.get("docs", [])}

    assert docs["docs/reference/governance_truth.generated.md"]["scope"] == "generated"
    assert docs["docs/reference/governance_truth.generated.md"]["layer"] == "render-only"
    assert docs["docs/open_source_runbook.md"]["manual_fact_enforced"] is True
    assert docs["docs/runner_contract.md"]["manual_fact_enforced"] is True
    assert docs["docs/mcp.md"]["command_smoke"] is True
    assert docs["docs/developer_guide.md"]["scope"] == "strict"


def test_governance_projection_blocks_and_reference_exist() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    usage = (REPO_ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    open_source = (REPO_ROOT / "docs" / "open_source_runbook.md").read_text(encoding="utf-8")
    runner = (REPO_ROOT / "docs" / "runner_contract.md").read_text(encoding="utf-8")
    reference = (REPO_ROOT / "docs" / "reference" / "governance_truth.generated.md").read_text(encoding="utf-8")

    assert "<!-- BEGIN GENERATED: root-release-identity -->" in readme
    assert "<!-- BEGIN GENERATED: script-readme-release-identity -->" in usage
    assert "<!-- BEGIN GENERATED: script-readme-governance-truth -->" in usage
    assert "<!-- BEGIN GENERATED: architecture-governance-truth -->" in architecture
    assert "<!-- BEGIN GENERATED: open-source-platform-truth -->" in open_source
    assert "<!-- BEGIN GENERATED: runner-contract-governance-truth -->" in runner
    assert "# Governance Truth Reference" in reference
    assert "## Done Signal Truth" in reference
    assert "## Hosted CI Contract" in reference
