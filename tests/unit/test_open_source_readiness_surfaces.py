from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_open_source_surface_files_exist() -> None:
    required = [
        "LICENSE",
        "NOTICE",
        "THIRD_PARTY_NOTICES.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "SUPPORT.md",
        "CODE_OF_CONDUCT.md",
        ".github/CODEOWNERS",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/documentation.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        "docs/architecture.md",
        "docs/usage.md",
        "docs/open_source_runbook.md",
    ]
    for rel in required:
        assert (REPO_ROOT / rel).exists(), rel


def test_pyproject_and_dependabot_reflect_open_source_defaults() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dependabot = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    package_json = (REPO_ROOT / "package.json").read_text(encoding="utf-8")

    assert 'license = {text = "MIT"}' in pyproject
    assert 'readme = "README.md"' in pyproject
    assert 'license-files = ["LICENSE", "NOTICE"]' in pyproject
    assert 'directory: "/"' in dependabot
    assert 'directory: "/apps/webui"' in dependabot
    assert '"public:readiness": "bash tooling/gates/public_readiness_gate.sh release"' in package_json
    assert '"platform:align": "bash tooling/gates/platform_alignment_gate.sh"' in package_json


def test_public_asset_provenance_contract_exists() -> None:
    assert (REPO_ROOT / "contracts" / "governance" / "public_asset_provenance.yaml").exists()
    assert (REPO_ROOT / "contracts" / "governance" / "public_artifact_policy.yaml").exists()


def test_readme_exposes_limited_maintenance_and_minimal_truth_routes() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version_match = re.search(r'^version = "([^"]+)"$', pyproject, flags=re.MULTILINE)
    assert version_match is not None
    version = version_match.group(1)

    assert "limited-maintenance open source" in readme
    assert "Minimal Truth Routes" in readme
    assert "docs/open_source_runbook.md" in readme
    assert "docs/usage.md" in readme
    assert "docs/architecture.md" in readme
    assert f'version = "{version}"' in pyproject
    assert "Current source package version" in readme
    assert "Current current-head release boundary" in readme
    assert version in readme
    assert "requires_local_release_evidence" in readme
    assert "Verified published closure" in readme
    assert "published_release_verified" in readme


def test_open_source_runbook_mentions_release_draft_entrypoint() -> None:
    runbook = (REPO_ROOT / "docs/open_source_runbook.md").read_text(encoding="utf-8")

    assert "npm run release:draft" in runbook
    assert "Platform Truth Surfaces (Dynamic Projection)" in runbook
    assert "gh repo view --json nameWithOwner,url,isPrivate,defaultBranchRef" in runbook
    assert "bash tooling/gates/public_readiness_gate.sh repo" in runbook
    assert "bash tooling/gates/public_readiness_gate.sh release" in runbook
    assert "bash tooling/gates/platform_alignment_gate.sh" in runbook
    assert "bash tooling/gates/public_artifact_audit.sh" in runbook
    assert "reference/governance_truth.generated.md" in runbook


def test_third_party_notices_points_to_public_artifact_audit_surface() -> None:
    notices = (REPO_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert "This file records the most important third-party dependencies" in notices
    assert "It is not a full SBOM" in notices
    assert "contracts/governance/public_asset_provenance.yaml" in notices
    assert "bash tooling/gates/public_artifact_audit.sh" in notices


def test_usage_is_a_detailed_operator_guide_not_a_second_public_overview() -> None:
    usage = (REPO_ROOT / "docs" / "usage.md").read_text(encoding="utf-8")

    assert "Detailed Operator Guide" in usage
    assert "This file is the detailed operator guide." in usage
    assert "README.md](../README.md)" in usage
    assert "docs/open_source_runbook.md" in usage


def test_issue_template_config_links_to_repo_specific_docs() -> None:
    config = (REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8")

    assert "movi-organizer/blob/main/SECURITY.md" in config
    assert "movi-organizer/blob/main/SUPPORT.md" in config


def test_open_source_runbook_explains_upstream_is_dependency_governance_here() -> None:
    runbook = (REPO_ROOT / "docs" / "open_source_runbook.md").read_text(encoding="utf-8")
    assert "public source repository" in runbook
