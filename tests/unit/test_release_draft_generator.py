from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_release_draft_generator_writes_expected_sections(tmp_path: Path) -> None:
    output = tmp_path / "release-draft.md"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "ci" / "prepare_release_draft.py"),
            "--root",
            str(REPO_ROOT),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    content = output.read_text(encoding="utf-8")
    assert "## Verified Gates" in content
    assert "bash tooling/gates/quality_gate.sh" in content
    assert "only delivery-complete signal" in content
    assert "repo-side governance scorecard only" in content
    assert "limited-maintenance open source" in content
    assert "## Platform-side Checklist" in content
    assert "## Platform-side Gaps" in content
    assert "Visibility:" in content
    assert "Current open-source surface files are committed and pushed to the default branch" in content
    assert "GitHub Release asset provenance / SBOM are not yet closed" in content
