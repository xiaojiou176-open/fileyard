from __future__ import annotations

import atexit
import os
import shutil
import sys
from pathlib import Path


def _default_machine_cache_root() -> Path:
    return Path(os.environ.get("GOVERNANCE_MACHINE_CACHE_ROOT", "~/.cache/fileman")).expanduser()


def _cleanup_local_pycache() -> None:
    shutil.rmtree(Path(__file__).resolve().parent / "__pycache__", ignore_errors=True)


def apply_runtime_hygiene() -> str:
    pycache_prefix = str(Path(os.environ.get("PYTHONPYCACHEPREFIX", _default_machine_cache_root() / "pycache")).expanduser())
    Path(pycache_prefix).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    os.environ.setdefault("PYTHONPYCACHEPREFIX", pycache_prefix)
    sys.dont_write_bytecode = True
    sys.pycache_prefix = pycache_prefix
    return pycache_prefix


apply_runtime_hygiene()
atexit.register(_cleanup_local_pycache)
