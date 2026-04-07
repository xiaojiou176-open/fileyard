from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _script_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _checker(script_root: Path) -> Path:
    return script_root / "tooling" / "scripts" / "check_precommit_strictness.py"


def _python_bin(script_root: Path) -> Path:
    repo_root = script_root.parent
    venv_python = repo_root / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def _run_checker(cwd: Path) -> subprocess.CompletedProcess[str]:
    script_root = _script_root()
    return subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def test_precommit_strictness_passes_without_soft_skip_warn(tmp_path: Path) -> None:
    (tmp_path / ".pre-commit-config.yaml").write_text(
        """
repos:
  - repo: local
    hooks:
      - id: strict-hook
        entry: bash -lc 'echo "ERROR tool missing"; exit 1'
        language: system
        stages: [pre-commit]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    proc = _run_checker(tmp_path)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "no soft-skip WARN patterns found" in out


def test_precommit_strictness_blocks_soft_skip_warn_pattern(tmp_path: Path) -> None:
    (tmp_path / ".pre-commit-config.yaml").write_text(
        """
repos:
  - repo: local
    hooks:
      - id: bad-soft-skip
        entry: bash -lc 'echo "WARN tool missing, skip check"; exit 0'
        language: system
        stages: [pre-commit]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    proc = _run_checker(tmp_path)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "found soft-skip WARN patterns" in out
    assert "bad-soft-skip" in out


def test_precommit_strictness_ignores_soft_skip_warn_outside_precommit_stage(tmp_path: Path) -> None:
    (tmp_path / ".pre-commit-config.yaml").write_text(
        """
repos:
  - repo: local
    hooks:
      - id: pre-push-warn
        entry: bash -lc 'echo "WARN tool missing, skip check"; exit 0'
        language: system
        stages: [pre-push]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    proc = _run_checker(tmp_path)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "no soft-skip WARN patterns found" in out
