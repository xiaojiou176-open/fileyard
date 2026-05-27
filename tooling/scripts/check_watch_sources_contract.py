#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate watch-source durable path contract")
    parser.add_argument("--root", default=".")
    parser.add_argument("--workspace-root", default="~/.fileorganize/workspaces/default")
    args = parser.parse_args()

    path = Path(args.workspace_root).expanduser() / ".fileorganize" / "preferences" / "watch_sources.json"
    issues: list[str] = []
    if ".fileorganize/preferences/" not in path.as_posix():
        issues.append(f"watch source path escaped preference root: {path}")
    if path.name != "watch_sources.json":
        issues.append(f"unexpected watch source filename: {path.name}")

    if issues:
        sys.stderr.write("watch-sources-contract gate failed\n")
        for item in issues:
            sys.stderr.write(f"- {item}\n")
        return 1

    print("watch-sources-contract gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
