from __future__ import annotations

import os
from pathlib import Path

from tooling.scripts.check_runtime_layout import _safe_walk_paths


def test_safe_walk_paths_ignores_transient_file_not_found(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "runtime-root"
    root.mkdir()
    stable_dir = root / "stable"
    stable_dir.mkdir()

    def _fake_walk(_root, onerror=None):
        if onerror is not None:
            onerror(FileNotFoundError("transient runtime tmp disappeared"))
        yield str(root), ["stable"], []
        yield str(stable_dir), [], ["ok.txt"]

    monkeypatch.setattr(os, "walk", _fake_walk)

    paths = _safe_walk_paths(root)

    assert stable_dir in paths
    assert stable_dir / "ok.txt" in paths
