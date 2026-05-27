#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

FEATURE_STATE_FILES = {
    "review_rules.json",
    "learned_rules.json",
    "watch_sources.json",
    "strategy_packs.json",
}
SKIP_PREFIXES = (".git/", ".runtime-cache/", ".agents/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when durable workbench state leaks outside <workspace-root>/.fileorganize")
    parser.add_argument("--root", default=".")
    parser.add_argument("--workspace-root", default=os.environ.get("FILEORGANIZE_WORKSPACE_ROOT", "~/.fileorganize/workspaces/default"))
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    issues: list[str] = []
    for path in repo_root.rglob("*.json"):
        rel = path.relative_to(repo_root).as_posix()
        if rel.startswith(SKIP_PREFIXES):
            continue
        if path.name not in FEATURE_STATE_FILES:
            continue
        issues.append(f"durable feature state leaked into repo tree: {rel}")

    if issues:
        sys.stderr.write("feature-state-layout gate failed\n")
        for item in issues:
            sys.stderr.write(f"- {item}\n")
        return 1

    print("feature-state-layout gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
