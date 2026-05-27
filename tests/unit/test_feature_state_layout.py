from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_feature_state_layout_script_passes_for_repo() -> None:
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_feature_state_layout.py"), "--root", str(REPO_ROOT)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "feature-state-layout gate passed" in proc.stdout
