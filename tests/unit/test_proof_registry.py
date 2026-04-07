from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_proof_registry_gate_passes_current_repo(tmp_path: Path) -> None:
    output = tmp_path / "proof-gate.txt"
    env = os.environ.copy()
    env["MOVI_ALLOW_HOST_EXECUTION"] = "1"

    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_proof_registry.py"),
            "--root",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    output.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    assert proc.returncode == 0, output.read_text(encoding="utf-8")
