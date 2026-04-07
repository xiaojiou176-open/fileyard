from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_docs_truth_routes_script_passes_for_current_repo() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_docs_truth_routes.py"),
            "--root",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "docs_truth_routes: passed" in result.stdout
