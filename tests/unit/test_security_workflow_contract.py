from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dependency_review_workflow_is_pinned_and_minimal() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "dependency-review.yml").read_text(encoding="utf-8")
    assert "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5" in workflow
    assert "actions/dependency-review-action@2031cfc080254a8a887f58cffee85186f0e49e48" in workflow
    assert "fail-on-severity: high" in workflow
    assert "pull-requests: read" in workflow


def test_codeql_workflow_is_pinned_and_targets_repo_languages() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "codeql.yml").read_text(encoding="utf-8")
    assert "github/codeql-action/init@38697555549f1db7851b81482ff19f1fa5c4fedc" in workflow
    assert "github/codeql-action/analyze@38697555549f1db7851b81482ff19f1fa5c4fedc" in workflow
    assert "languages: python,javascript" in workflow
    assert "security-events: write" in workflow


def test_scorecards_workflow_is_pinned_and_uploads_sarif() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "scorecards.yml").read_text(encoding="utf-8")
    assert "ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a" in workflow
    assert "github/codeql-action/upload-sarif@38697555549f1db7851b81482ff19f1fa5c4fedc" in workflow
    assert "publish_results: true" in workflow
    assert "results_format: sarif" in workflow
    assert "id-token: write" in workflow
