from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dependency_review_workflow_is_minimal_and_pinned() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "dependency-review.yml").read_text(encoding="utf-8")

    assert "name: dependency-review" in workflow
    assert "pull_request:" in workflow
    assert "types: [opened, synchronize, reopened, ready_for_review]" in workflow
    assert "permissions:" in workflow
    assert "contents: read" in workflow
    assert "pull-requests: read" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5" in workflow
    assert "actions/dependency-review-action@2031cfc080254a8a887f58cffee85186f0e49e48" in workflow
    assert "fail-on-severity: high" in workflow
    assert "retry-on-snapshot-warnings: true" in workflow
    assert "retry-on-snapshot-warnings-timeout: 180" in workflow
    assert "pull_request_target" not in workflow
    assert "workflow_dispatch" not in workflow
    assert "write" not in workflow
