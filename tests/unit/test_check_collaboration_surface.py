from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MINIMAL_SECURITY_TEXT = (
    "\n".join(
        [
            "# Security Policy",
            "GitHub Private Vulnerability Reporting is the primary private reporting channel for this repository.",
            "No separate fallback private email is currently configured for this repository.",
            "Do not report security vulnerabilities in public GitHub issues.",
        ]
    )
    + "\n"
)


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def test_collaboration_surface_checker_passes_for_repo_surface() -> None:
    proc = _run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_collaboration_surface.py"),
            "--root",
            str(REPO_ROOT),
        ],
        REPO_ROOT,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "collaboration-surface: passed" in out


def test_collaboration_surface_checker_fails_close_on_non_english_or_missing_private_channel(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True)
    (repo / "contracts" / "governance").mkdir(parents=True)

    (repo / "contracts" / "governance" / "collaboration_surface_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "global_forbidden_regex:",
                '  - "[\\\\u4e00-\\\\u9fff]"',
                "targets:",
                "  - path: SECURITY.md",
                "    required_substrings:",
                '      - "# Security Policy"',
                '      - "No separate fallback private email is currently configured for this repository."',
                "    forbidden_substrings:",
                '      - "placeholder private contact channel"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "SECURITY.md").write_text(
        "# Security Policy\nplaceholder private contact channel\n请联系维护者\n",
        encoding="utf-8",
    )

    proc = _run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_collaboration_surface.py"),
            "--root",
            str(repo),
            "--policy",
            "contracts/governance/collaboration_surface_policy.yaml",
        ],
        repo,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "collaboration-surface: failed" in out
    assert "missing required text" in out
    assert "forbidden text present" in out
    assert "matched forbidden pattern" in out
