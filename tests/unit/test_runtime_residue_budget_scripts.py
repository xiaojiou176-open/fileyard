from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


def _prepare_repo(tmp_path: Path) -> Path:
    source_root = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    (repo / "contracts" / "runtime").mkdir(parents=True)
    (repo / "tooling" / "scripts").mkdir(parents=True)
    (repo / "apps" / "webui" / "node_modules").mkdir(parents=True)
    (repo / "tooling" / "__pycache__").mkdir(parents=True)
    (repo / "tooling" / "__pycache__" / "ghost.pyc").write_bytes(b"pyc")

    contract = yaml.safe_load((source_root / "contracts" / "runtime" / "filesystem_layout.yaml").read_text(encoding="utf-8"))
    (repo / "contracts" / "runtime" / "filesystem_layout.yaml").write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )

    for name in ("check_repo_runtime_residue.py", "check_runtime_budget.py"):
        src = source_root / "tooling" / "scripts" / name
        dst = repo / "tooling" / "scripts" / name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    return repo


def test_runtime_residue_scripts_ignore_empty_node_modules_and_cleanup_tooling_pycache(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path)

    residue = subprocess.run(
        [sys.executable, str(repo / "tooling" / "scripts" / "check_repo_runtime_residue.py"), "--root", str(repo)],
        text=True,
        capture_output=True,
        check=False,
    )
    budget = subprocess.run(
        [sys.executable, str(repo / "tooling" / "scripts" / "check_runtime_budget.py"), "--root", str(repo)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert residue.returncode == 0, residue.stdout + residue.stderr
    assert budget.returncode == 0, budget.stdout + budget.stderr
    assert not (repo / "tooling" / "__pycache__").exists()
    assert (repo / "apps" / "webui" / "node_modules").exists()
    assert list((repo / "apps" / "webui" / "node_modules").iterdir()) == []
