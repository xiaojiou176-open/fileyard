from __future__ import annotations

import re
from pathlib import Path

from packages.domain.pipeline_config import APP_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_app_version_matches_pyproject_project_version() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)

    assert match, "pyproject.toml must define [project].version"
    assert APP_VERSION == match.group(1)
