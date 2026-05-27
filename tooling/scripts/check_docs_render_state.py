#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _apply_runtime_hygiene() -> None:
    pycache_prefix = str(Path(os.environ.get("PYTHONPYCACHEPREFIX", "~/.cache/fileman/pycache")).expanduser())
    Path(pycache_prefix).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    os.environ.setdefault("PYTHONPYCACHEPREFIX", pycache_prefix)
    sys.dont_write_bytecode = True
    sys.pycache_prefix = pycache_prefix


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify render-only docs and generated fragments are current.")
    parser.add_argument("--root", default=".", help="Repository root")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.root).resolve()
    _apply_runtime_hygiene()
    from docs_render_lib import build_render_outputs

    expected, _ = build_render_outputs(repo_root)
    stale: list[str] = []
    missing: list[str] = []
    for rel_path, rendered in expected.items():
        target = repo_root / rel_path
        if not target.exists():
            missing.append(rel_path)
            continue
        if target.read_text(encoding="utf-8") != rendered:
            stale.append(rel_path)
    if missing or stale:
        print("❌ docs_render_state: stale or missing rendered outputs")
        for rel_path in missing:
            print(f"- missing: {rel_path}")
        for rel_path in stale:
            print(f"- stale: {rel_path}")
        print("fix: python3 tooling/scripts/render_docs.py")
        return 1
    print("✅ docs_render_state: passed")
    print(f"checked_outputs={len(expected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
