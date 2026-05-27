#!/usr/bin/env python3
"""Block legacy path and entrypoint strings from re-entering active surfaces."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".sh",
    ".yml",
    ".yaml",
    ".toml",
    ".json",
    ".jsonc",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
}

SKIP_DIRS = {
    ".git",
    ".runtime-cache",
    ".agent",
    ".agents",
    ".codex",
    ".claude",
    ".vscode",
    "docs/_archive",
    "apps/webui/node_modules",
    "node_modules",
}

SKIP_FILES = {
    "package-lock.json",
    "apps/webui/package-lock.json",
    "tooling/scripts/check_active_legacy_sweep.py",
}

PUBLIC_GUIDE_PATHS = {
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/usage.md",
    "docs/architecture.md",
    "docs/AGENTS.md",
    "docs/CLAUDE.md",
    "tests/AGENTS.md",
    "tests/CLAUDE.md",
}

LEGACY_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "legacy-script-tree",
        re.compile(r"脚本/(?:README\.md|config|docs|pipeline|requirements|scripts|tests|fileman\.py|manifest\.schema\.json)"),
        "replace legacy 脚本/* references with current tooling/contracts/docs/packages/tests paths",
    ),
    (
        "legacy-root-webui-tree",
        re.compile(r"(?<!apps/)webui/"),
        "replace legacy root webui/* references with apps/webui/*",
    ),
    (
        "legacy-webui-dist",
        re.compile(r"\.runtime-cache/apps/webui/build|webui/dist"),
        "replace legacy dist output with .runtime-cache/build/apps/webui",
    ),
    (
        "legacy-root-env-copy",
        re.compile(r"cp\s+\.env\.example\s+\.env"),
        "copy .env.example to workspace runtime env file instead of repo-root .env",
    ),
    (
        "legacy-root-env-source",
        re.compile(r"source\s+(?:\.\./)?\.env\b"),
        "source the workspace runtime env file instead of repo-root .env",
    ),
    (
        "legacy-root-env-path",
        re.compile(r'(?:REPO_ROOT\s*/\s*"\.env"|仓库根目录 [`\"]?\.env[`\"]?(?![A-Za-z0-9_.-])|\.env not found at)'),
        "remove repo-root .env as an active runtime secret source",
    ),
    (
        "legacy-mutmut-root",
        re.compile(r"(?<!/)\.mutmut-cache\b"),
        "use .runtime-cache/test/mutation/.mutmut-cache as the only mutmut cache path",
    ),
    (
        "legacy-module-namespace",
        re.compile(r"packages\.core\.pipeline(?=[.:])"),
        "use apps.api.* / apps.cli.* / packages.* for runtime/import/module strings",
    ),
    (
        "legacy-core-pipeline-path",
        re.compile(r"packages/core/pipeline"),
        "replace packages/core/pipeline with packages/application|packages/domain|packages/infrastructure|packages/observability",
    ),
    (
        "legacy-dotvenv-bin",
        re.compile(r"\.venv/bin/python"),
        "replace .venv/bin/python with shell entrypoints or the canonical runtime venv",
    ),
    (
        "legacy-public-dot-scripts",
        re.compile(r"\./scripts/"),
        "replace ./scripts/* public commands with tooling/runtime|gates|docs|cleanup|ci|upstreams entrypoints",
    ),
    (
        "legacy-public-tooling-module-docs",
        re.compile(r"tooling/scripts/(?:AGENTS|CLAUDE)\.md"),
        "replace tooling/scripts module docs with tooling/AGENTS.md and tooling/CLAUDE.md",
    ),
    (
        "legacy-public-tooling-surface",
        re.compile(r"tooling/scripts/"),
        "do not advertise tooling/scripts as a public surface; use tooling/runtime|gates|docs|cleanup|ci|upstreams",
    ),
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root to scan.")
    return parser.parse_args(argv)


def _should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if rel in SKIP_FILES:
        return True
    return any(rel == skip or rel.startswith(f"{skip}/") for skip in SKIP_DIRS)


def _iter_candidate_files(root: Path) -> list[Path]:
    result: list[Path] = []

    def _ignore_walk_error(_error: OSError) -> None:
        # quality_gate can scan while pytest/runtime tmp directories are being
        # removed; disappearing runtime residue should not fail active sweep.
        return None

    for current_root, dirnames, filenames in os.walk(root, topdown=True, onerror=_ignore_walk_error):
        current_path = Path(current_root)
        dirnames[:] = [name for name in dirnames if not _should_skip(current_path / name, root)]
        for filename in filenames:
            path = current_path / filename
            if _should_skip(path, root):
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            result.append(path)
    return result


def _is_public_guide(rel: str) -> bool:
    return rel in PUBLIC_GUIDE_PATHS


def _scan_file(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        return []
    failures: list[str] = []
    for label, pattern, hint in LEGACY_PATTERNS:
        for lineno, line in enumerate(text.splitlines(), start=1):
            if label.startswith("legacy-public-") and not _is_public_guide(rel):
                continue
            if rel.startswith("tests/"):
                continue
            if label == "legacy-root-webui-tree" and rel == "docs/usage.md" and "│  └─ webui/" in line:
                continue
            if label == "legacy-root-webui-tree" and rel == "contracts/governance/module_graph.yaml" and "webui/**" in line:
                continue
            if label == "legacy-root-webui-tree" and "contracts/api/generated/webui/" in line:
                continue
            if label == "legacy-dotvenv-bin" and rel.startswith("tests/"):
                continue
            if label == "legacy-public-tooling-surface" and "tooling/scripts/ 为内部实现层" in line:
                continue
            if not pattern.search(line):
                continue
            failures.append(f"{rel}:{lineno}: [{label}] {line.strip()} :: fix={hint}")
    return failures


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    root = Path(args.root).resolve()
    failures: list[str] = []
    for path in _iter_candidate_files(root):
        failures.extend(_scan_file(path, root))

    if failures:
        print("❌ active_legacy_sweep: legacy paths/entrypoints remain in active surfaces")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("✅ active_legacy_sweep: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
