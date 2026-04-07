from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_plans_readme_points_to_current_authoritative_plan() -> None:
    plans_readme = REPO_ROOT / ".agents" / "Plans" / "README.md"
    if not plans_readme.exists():
        pytest.skip(".agents/Plans/README.md is not shipped in clean public checkouts")
    readme = plans_readme.read_text(encoding="utf-8")
    assert "2026-03-29_09-13-55__manifest-workbench-final-form-master-plan.md" in readme
    assert "current source of truth for active execution status" in readme
    assert "historical-only context" in readme
