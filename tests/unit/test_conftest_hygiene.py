from __future__ import annotations

import os
from pathlib import Path

import conftest as repo_conftest


def test_prune_repo_bytecode_residue_ignores_transient_missing_dirs(tmp_path: Path, monkeypatch) -> None:
    missing_dir = tmp_path / "apps" / "webui" / "node_modules" / "__pycache__"
    missing_dir.mkdir(parents=True)

    original_walk = os.walk

    def flaky_walk(top, topdown=False, onerror=None, followlinks=False):  # type: ignore[no-untyped-def]
        if Path(top) == tmp_path / "apps":
            if onerror is not None:
                onerror(FileNotFoundError(str(missing_dir)))
            yield str(missing_dir.parent), ["__pycache__"], []
            return
        yield from original_walk(top, topdown=topdown, onerror=onerror, followlinks=followlinks)

    monkeypatch.setattr(repo_conftest, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(repo_conftest.os, "walk", flaky_walk)

    repo_conftest._prune_repo_bytecode_residue()

    assert not missing_dir.exists()
    assert missing_dir.parent.exists()
