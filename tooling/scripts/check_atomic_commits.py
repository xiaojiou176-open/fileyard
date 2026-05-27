#!/usr/bin/env python3
"""Enforce atomic commit size limits (files/lines), with allowlist support."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ZERO_SHA = "0" * 40
CURRENT_REPO_ROOT = REPO_ROOT
MODERN_BASELINE_PATH = REPO_ROOT / "contracts" / "governance" / "baselines" / "gate_history_baseline.json"
LEGACY_BASELINE_PATH = REPO_ROOT / "脚本" / "config" / "governance-baselines" / "gate_history_baseline.json"
DEFAULT_ALLOWLIST: tuple[str, ...] = ("requirements.lock.txt", "requirements-dev.lock.txt")


@dataclass(frozen=True)
class CommitStat:
    sha: str
    subject: str
    files: int
    lines: int


def _parse_env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be integer, got: {raw}") from exc
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got: {value}")
    return value


def _run_git(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=CURRENT_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def _run_git_ref(args: list[str]) -> str:
    return _run_git(args).strip()


def _first_ref_line(raw: str) -> str:
    for line in raw.splitlines():
        candidate = line.strip()
        if candidate:
            return candidate
    return ""


def _resolve_default_from_ref() -> str:
    try:
        upstream = _run_git_ref(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    except subprocess.CalledProcessError:
        upstream = ""

    if upstream:
        try:
            return _run_git_ref(["merge-base", "HEAD", upstream])
        except subprocess.CalledProcessError:
            pass

    for candidate in ("refs/remotes/origin/HEAD", "origin/main", "origin/master"):
        try:
            remote_ref = _run_git_ref(["symbolic-ref", "--short", candidate]) if candidate == "refs/remotes/origin/HEAD" else candidate
            if remote_ref:
                return _run_git_ref(["merge-base", "HEAD", remote_ref])
        except subprocess.CalledProcessError:
            continue

    roots_raw = _run_git_ref(["rev-list", "--max-parents=0", "HEAD"])
    first_root = _first_ref_line(roots_raw)
    if first_root:
        return first_root
    return _run_git_ref(["rev-parse", "HEAD"])


def _parse_allowlist(raw_items: list[str]) -> list[str]:
    patterns: list[str] = []
    for item in raw_items:
        for part in item.split(","):
            pattern = part.strip()
            if pattern:
                patterns.append(pattern)
    return patterns


def _load_legacy_atomic_allowlist() -> set[str]:
    baseline_path = MODERN_BASELINE_PATH if MODERN_BASELINE_PATH.exists() else LEGACY_BASELINE_PATH
    if not baseline_path.exists():
        return set()
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    values = data.get("legacy_non_atomic_commits", [])
    if not isinstance(values, list):
        return set()
    return {str(item).strip() for item in values if str(item).strip()}


def _staged_stat(allowlist: list[str]) -> tuple[int, int]:
    output = _run_git(["diff", "--cached", "--numstat"])
    files = 0
    lines = 0
    for raw in output.splitlines():
        parts = raw.strip().split("\t")
        if len(parts) < 3:
            continue
        added_text, deleted_text, path = parts[0], parts[1], parts[2].replace("\\", "/")
        if _is_allowlisted(path, allowlist):
            continue
        files += 1
        added = 0 if added_text == "-" else int(added_text)
        deleted = 0 if deleted_text == "-" else int(deleted_text)
        lines += added + deleted
    return files, lines


def _resolve_refs(from_ref: str | None, to_ref: str | None) -> tuple[str, str]:
    if from_ref and from_ref != ZERO_SHA:
        return _first_ref_line(from_ref), to_ref or "HEAD"

    env_from = os.getenv("PRE_COMMIT_FROM_REF", "").strip()
    env_to = os.getenv("PRE_COMMIT_TO_REF", "").strip()
    if env_from and env_from != ZERO_SHA:
        return _first_ref_line(env_from), env_to or "HEAD"

    return _resolve_default_from_ref(), to_ref or env_to or "HEAD"


def _list_commits(from_ref: str, to_ref: str, include_merges: bool) -> list[tuple[str, str]]:
    args = ["rev-list", "--reverse", f"{from_ref}..{to_ref}"]
    if not include_merges:
        args.insert(1, "--no-merges")
    shas = [line.strip() for line in _run_git(args).splitlines() if line.strip()]
    commits: list[tuple[str, str]] = []
    for sha in shas:
        subject = _run_git(["show", "-s", "--format=%s", sha]).strip()
        commits.append((sha, subject))
    return commits


def _is_allowlisted(path: str, allowlist: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in allowlist)


def _commit_stat(sha: str, subject: str, allowlist: list[str]) -> CommitStat:
    output = _run_git(["show", "--numstat", "--format=", sha])
    files = 0
    lines = 0
    for raw in output.splitlines():
        parts = raw.strip().split("\t")
        if len(parts) < 3:
            continue
        added_text, deleted_text, path = parts[0], parts[1], parts[2].replace("\\", "/")
        if _is_allowlisted(path, allowlist):
            continue
        files += 1
        added = 0 if added_text == "-" else int(added_text)
        deleted = 0 if deleted_text == "-" else int(deleted_text)
        lines += added + deleted
    return CommitStat(sha=sha, subject=subject, files=files, lines=lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Git repository root (default: project root).",
    )
    parser.add_argument("--from-ref", help="Git ref start (defaults to pre-push env or HEAD~1).")
    parser.add_argument("--to-ref", default="HEAD", help="Git ref end (default: HEAD).")
    parser.add_argument(
        "--pre-push-auto",
        action="store_true",
        help="Resolve refs from PRE_COMMIT_FROM_REF/PRE_COMMIT_TO_REF or fallback defaults.",
    )
    parser.add_argument(
        "--mode",
        choices=("commit-range", "staged"),
        default="commit-range",
        help="commit-range (default) checks commits; staged checks current index diff.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=_parse_env_int("FILEORGANIZE_ATOMIC_MAX_FILES", 40),
        help="Per-commit max changed files (excluding allowlist).",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=_parse_env_int("FILEORGANIZE_ATOMIC_MAX_LINES", 4500),
        help="Per-commit max changed lines add+del (excluding allowlist).",
    )
    parser.add_argument(
        "--allowlist",
        action="append",
        default=[],
        help="Glob pattern(s) excluded from counting. Repeat or use comma-separated values.",
    )
    parser.add_argument(
        "--include-merges",
        action="store_true",
        help="Include merge commits in checks (default: false).",
    )
    parser.add_argument(
        "--require-non-empty-range",
        action="store_true",
        help="Fail when commit range resolves to zero commits (strict mode).",
    )
    return parser


def main(argv: list[str]) -> int:
    global CURRENT_REPO_ROOT
    parser = _build_parser()
    args = parser.parse_args(argv)
    CURRENT_REPO_ROOT = Path(args.repo_root).resolve()

    if args.max_files < 1 or args.max_lines < 1:
        parser.error("--max-files and --max-lines must be >= 1")

    allowlist = _parse_allowlist(args.allowlist)
    allowlist.extend(DEFAULT_ALLOWLIST)
    allowlist.extend(_parse_allowlist([os.getenv("FILEORGANIZE_ATOMIC_ALLOWLIST", "")]))

    if args.mode == "staged":
        try:
            files, lines = _staged_stat(allowlist)
        except subprocess.CalledProcessError as exc:
            print(f"❌ atomic-commit gate: failed to inspect staged diff: {exc}", file=sys.stderr)
            return 2
        if files == 0 and lines == 0:
            print("atomic-commit gate: no staged changes to check")
            return 0
        if files > args.max_files or lines > args.max_lines:
            print("❌ atomic-commit gate: failed (staged)")
            print(f"- thresholds: files <= {args.max_files}, lines <= {args.max_lines} (allowlist excluded)")
            print(f"- staged: files={files}, lines={lines}")
            if allowlist:
                print(f"- allowlist: {', '.join(allowlist)}")
            return 1
        print(f"✅ atomic-commit gate: passed (staged files={files}, lines={lines}, files<={args.max_files}, lines<={args.max_lines})")
        if allowlist:
            print(f"allowlist: {', '.join(allowlist)}")
        return 0

    if args.pre_push_auto:
        from_ref, to_ref = _resolve_refs(None, args.to_ref)
    else:
        from_ref, to_ref = _resolve_refs(args.from_ref, args.to_ref)

    try:
        commits = _list_commits(from_ref, to_ref, include_merges=args.include_merges)
    except subprocess.CalledProcessError as exc:
        print(f"❌ atomic-commit gate: failed to enumerate commits: {exc}", file=sys.stderr)
        return 2

    if not commits:
        if args.require_non_empty_range:
            print("❌ atomic-commit gate: failed")
            print(f"- no commits found in range: {from_ref}...{to_ref}")
            print("- reason: empty range is blocked in strict mode (--require-non-empty-range)")
            return 1
        print(f"⚠️ atomic-commit gate: no commits to check in range {from_ref}...{to_ref} (compat mode pass)")
        print("hint: enable --require-non-empty-range to fail on empty commit ranges")
        return 0

    failures: list[CommitStat] = []
    checked = 0
    legacy_allowlist = _load_legacy_atomic_allowlist()
    for sha, subject in commits:
        if sha in legacy_allowlist:
            continue
        try:
            stat = _commit_stat(sha, subject, allowlist)
        except subprocess.CalledProcessError as exc:
            print(f"❌ atomic-commit gate: failed to inspect {sha[:12]}: {exc}", file=sys.stderr)
            return 2
        checked += 1
        if stat.files > args.max_files or stat.lines > args.max_lines:
            failures.append(stat)

    if failures:
        print("❌ atomic-commit gate: failed")
        print(f"- thresholds: files <= {args.max_files}, lines <= {args.max_lines} (allowlist excluded)")
        if allowlist:
            print(f"- allowlist: {', '.join(allowlist)}")
        for item in failures:
            print(f"- {item.sha[:12]} {item.subject} | files={item.files}, lines={item.lines}")
        return 1

    skipped = len(commits) - checked
    print(
        f"✅ atomic-commit gate: passed ({checked} commits, files<={args.max_files}, lines<={args.max_lines}"
        f"{', legacy_skipped=' + str(skipped) if skipped else ''})"
    )
    if allowlist:
        print(f"allowlist: {', '.join(allowlist)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
