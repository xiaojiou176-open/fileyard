from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLANS_README = REPO_ROOT / ".agents" / "Plans" / "README.md"
OLD_REPO_FRAGMENT = "[其他项目]Useful_Tools/🗂️文件自动分类重命名"


def _current_authoritative_plan_path() -> Path:
    if not PLANS_README.exists():
        pytest.skip(".agents/Plans/README.md is not shipped in clean public checkouts")
    readme = PLANS_README.read_text(encoding="utf-8")
    match = re.search(r"- `([^`]+__.+?master-plan\.md)`", readme)
    assert match, "plans README must point to a current authoritative plan"
    return REPO_ROOT / ".agents" / "Plans" / match.group(1)


def test_current_authoritative_plan_uses_current_repo_path() -> None:
    plan_path = _current_authoritative_plan_path()
    content = plan_path.read_text(encoding="utf-8")

    assert "<repo-root>" in content
    assert str(REPO_ROOT) not in content
    assert OLD_REPO_FRAGMENT not in content


def test_current_truth_entrypoints_do_not_point_back_to_old_repo_path() -> None:
    readme = REPO_ROOT / "README.md"
    paths = [readme]
    if PLANS_README.exists():
        paths.append(PLANS_README)

    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert OLD_REPO_FRAGMENT not in content, f"{path} should not reference the old repo path"
