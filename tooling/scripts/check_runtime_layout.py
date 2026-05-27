#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"invalid yaml: {path}")
    return data


def _resolve(raw: str, repo_root: Path) -> Path:
    expanded = os.path.expanduser(raw)
    if expanded.startswith("/"):
        return Path(expanded)
    return repo_root / expanded


def _safe_walk_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []

    def _ignore_walk_error(exc: OSError) -> None:
        # Runtime tmp directories can disappear while the gate is traversing them.
        if isinstance(exc, FileNotFoundError):
            return
        raise exc

    paths: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root, onerror=_ignore_walk_error):
        current = Path(current_root)
        for dirname in dirnames:
            paths.append(current / dirname)
        for filename in filenames:
            paths.append(current / filename)
    return paths


def _collect_repo_residue(root: Path, patterns: list[str]) -> list[Path]:
    matches: list[Path] = []
    for pattern in patterns:
        try:
            candidates = sorted(root.glob(pattern))
        except FileNotFoundError:
            continue
        for found in candidates:
            if not found.exists():
                continue
            rel = found.relative_to(root).as_posix()
            if found.is_dir() and rel.startswith("apps/") and rel.endswith("/node_modules"):
                try:
                    next(found.iterdir())
                except StopIteration:
                    continue
                except FileNotFoundError:
                    continue
            if rel.startswith(".runtime-cache/") or rel.startswith(".git/") or rel.startswith(".agents/"):
                continue
            if any(parent == existing or parent in existing.parents for existing in matches for parent in [found]):
                continue
            if any(existing in found.parents for existing in matches):
                continue
            matches.append(found)
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate strict runtime filesystem layout")
    parser.add_argument("--root", default=".")
    parser.add_argument("--contract", default="contracts/runtime/filesystem_layout.yaml")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    contract = _load_yaml(repo_root / args.contract)
    issues: list[str] = []

    runtime_root = repo_root / ".runtime-cache"
    allowed_top_level = set(str(item) for item in contract.get("repo_runtime", {}).get("allowed_top_level", []))
    allowed_paths = set(str(item) for item in contract.get("repo_runtime", {}).get("allowed_paths", []))
    recursive_allowed_roots = set(str(item) for item in contract.get("repo_runtime", {}).get("recursive_allowed_roots", []))
    forbidden_roots = [str(item) for item in contract.get("repo_runtime", {}).get("forbidden_roots", [])]
    forbidden_repo_residue_globs = [str(item) for item in contract.get("repo_runtime", {}).get("forbidden_repo_residue_globs", [])]

    if not runtime_root.exists():
        issues.append("missing repo runtime root: .runtime-cache")
    else:
        for entry in sorted(runtime_root.iterdir()):
            if entry.name not in allowed_top_level:
                issues.append(f"unexpected .runtime-cache top-level entry: {entry.name}")
        for path in sorted(_safe_walk_paths(runtime_root)):
            rel = path.relative_to(repo_root).as_posix()
            if path.is_dir() and rel not in allowed_paths and not any(rel.startswith(f"{allowed}/") for allowed in recursive_allowed_roots):
                issues.append(f"unexpected runtime directory: {rel}")

    for raw in forbidden_roots:
        if any(ch in raw for ch in "*?[]"):
            base, _, suffix = raw.partition("**")
            base_path = repo_root / base.rstrip("/")
            if base_path.exists():
                for found in _safe_walk_paths(base_path):
                    if found.name == ".cache" or found.name == ".runtime-cache":
                        issues.append(f"forbidden runtime residue exists: {found.relative_to(repo_root).as_posix()}")
            continue
        path = _resolve(raw, repo_root)
        if path.exists():
            issues.append(f"forbidden runtime residue exists: {path.relative_to(repo_root).as_posix()}")

    for found in _collect_repo_residue(repo_root, forbidden_repo_residue_globs):
        issues.append(f"forbidden repo runtime residue exists: {found.relative_to(repo_root).as_posix()}")

    for raw in contract.get("machine_cache", {}).get("required_paths", []):
        if not _resolve(str(raw), repo_root).exists():
            issues.append(f"missing machine cache path: {raw}")

    for key in ("workspace_root", "fileman_root", "manifest_root", "artifact_root", "run_bundle_root", "env_root"):
        raw = contract.get("workspace_runtime", {}).get(key)
        if not raw:
            issues.append(f"workspace runtime missing contract field: {key}")
            continue
        target = _resolve(str(raw), repo_root)
        if not target.exists():
            issues.append(f"missing workspace runtime path: {target}")

    if issues:
        sys.stderr.write("runtime-layout gate failed\n")
        for issue in issues:
            sys.stderr.write(f"- {issue}\n")
        return 1

    print("runtime-layout gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
