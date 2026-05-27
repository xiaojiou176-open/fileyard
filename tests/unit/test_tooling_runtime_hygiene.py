from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from tooling.scripts.score_repo_governance import _governance_python_env

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_sitecustomize_module():
    module_path = REPO_ROOT / "tooling" / "scripts" / "sitecustomize.py"
    spec = importlib.util.spec_from_file_location("movi_tooling_sitecustomize_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_score_governance_env_sets_repo_safe_python_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)

    env = _governance_python_env()

    expected = tmp_path / ".cache" / "fileyard" / "pycache"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PYTHONPYCACHEPREFIX"] == str(expected)
    assert expected.exists()


def test_tooling_sitecustomize_redirects_pycache_to_machine_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)

    previous_prefix = sys.pycache_prefix
    previous_env = os.environ.get("PYTHONPYCACHEPREFIX")
    try:
        module = _load_sitecustomize_module()
        applied = module.apply_runtime_hygiene()
        expected = tmp_path / ".cache" / "fileyard" / "pycache"
        assert applied == str(expected)
        assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
        assert os.environ["PYTHONPYCACHEPREFIX"] == str(expected)
        assert sys.dont_write_bytecode is True
        assert sys.pycache_prefix == str(expected)
        assert expected.exists()
    finally:
        sys.pycache_prefix = previous_prefix
        if previous_env is None:
            os.environ.pop("PYTHONPYCACHEPREFIX", None)
        else:
            os.environ["PYTHONPYCACHEPREFIX"] = previous_env


def test_repo_root_sitecustomize_redirects_pycache_to_machine_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)

    previous_prefix = sys.pycache_prefix
    previous_env = os.environ.get("PYTHONPYCACHEPREFIX")
    try:
        module_path = REPO_ROOT / "sitecustomize.py"
        spec = importlib.util.spec_from_file_location("movi_root_sitecustomize_test", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        applied = module.apply_runtime_hygiene()
        expected = tmp_path / ".cache" / "fileyard" / "pycache"
        assert applied == str(expected)
        assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
        assert os.environ["PYTHONPYCACHEPREFIX"] == str(expected)
        assert sys.dont_write_bytecode is True
        assert sys.pycache_prefix == str(expected)
        assert expected.exists()
    finally:
        sys.pycache_prefix = previous_prefix
        if previous_env is None:
            os.environ.pop("PYTHONPYCACHEPREFIX", None)
        else:
            os.environ["PYTHONPYCACHEPREFIX"] = previous_env


def test_repo_root_sitecustomize_cleans_repo_local_pycache(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sitecustomize_path = repo / "sitecustomize.py"
    sitecustomize_path.write_text((REPO_ROOT / "sitecustomize.py").read_text(encoding="utf-8"), encoding="utf-8")
    stale = repo / "tooling" / "scripts" / "__pycache__"
    stale.mkdir(parents=True)
    (stale / "marker.pyc").write_text("x", encoding="utf-8")

    spec = importlib.util.spec_from_file_location("movi_root_sitecustomize_cleanup_test", sitecustomize_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module._cleanup_repo_local_pycache()
    assert not stale.exists()
