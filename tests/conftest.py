from __future__ import annotations

import atexit
import importlib.util
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _iter_named_dirs(root: Path, target_name: str) -> list[Path]:
    matches: list[Path] = []

    def _on_error(exc: OSError) -> None:
        # Frontend install / cleanup can transiently delete nested node_modules
        # entries while pytest startup is pruning bytecode residue. Missing
        # directories should not abort the whole session-level hygiene pass.
        if isinstance(exc, FileNotFoundError):
            return
        raise exc

    for dirpath, dirnames, _filenames in os.walk(root, topdown=False, onerror=_on_error):
        base = Path(dirpath)
        for dirname in dirnames:
            if dirname == target_name:
                matches.append(base / dirname)
    return matches


def _prune_repo_bytecode_residue() -> None:
    managed_roots = [REPO_ROOT / "apps", REPO_ROOT / "packages", REPO_ROOT / "tests", REPO_ROOT / "tooling"]
    for pattern in ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"):
        for root in managed_roots:
            if not root.exists():
                continue
            for path in _iter_named_dirs(root, pattern):
                if path.exists() and path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
        for path in REPO_ROOT.glob(pattern):
            if path.exists() and path.is_dir():
                shutil.rmtree(path, ignore_errors=True)


def _apply_test_runtime_hygiene() -> None:
    pycache_prefix = Path(os.environ.get("PYTHONPYCACHEPREFIX", "~/.cache/fileorganize/pycache")).expanduser()
    coverage_dir = REPO_ROOT / ".runtime-cache" / "test" / "coverage"
    pycache_prefix.mkdir(parents=True, exist_ok=True)
    coverage_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    os.environ.setdefault("PYTHONPYCACHEPREFIX", str(pycache_prefix))
    sys.dont_write_bytecode = True
    sys.pycache_prefix = str(pycache_prefix)


_apply_test_runtime_hygiene()
atexit.register(_prune_repo_bytecode_residue)


def _load_tests_helper(module_name: str, filename: str):
    helper_path = REPO_ROOT / "tests" / filename
    spec = importlib.util.spec_from_file_location(module_name, helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载测试 helper: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_apply_changes_compat = _load_tests_helper("tests_apply_changes_compat", "_apply_changes_compat.py")
_apply_changes_compat.install_apply_changes_test_compat()


def pytest_sessionstart(session) -> None:  # type: ignore[no-untyped-def]
    _prune_repo_bytecode_residue()


def pytest_sessionfinish(session, exitstatus) -> None:  # type: ignore[no-untyped-def]
    _prune_repo_bytecode_residue()
