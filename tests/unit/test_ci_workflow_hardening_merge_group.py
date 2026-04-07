from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_ci_workflow_hardening_requires_merge_group_trigger(tmp_path: Path) -> None:
    repo_root = _repo_root()
    workflow_src = repo_root / ".github" / "workflows" / "ci.yml"
    workflow_copy = tmp_path / "ci.yml"
    workflow_copy.write_text(
        workflow_src.read_text(encoding="utf-8").replace("  merge_group:\n    types: [checks_requested]\n", ""),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(repo_root / "tooling" / "scripts" / "check_ci_workflow_hardening.py"), "--workflow", str(workflow_copy)],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 1
    output = proc.stdout + proc.stderr
    assert "workflow.on must declare merge_group trigger" in output
