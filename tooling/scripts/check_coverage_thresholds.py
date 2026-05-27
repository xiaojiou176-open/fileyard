#!/usr/bin/env python3
"""Check overall and key-module coverage thresholds from coverage.xml.

Used by quality_gate / pre-push coverage enforcement.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_TOTAL_MIN = 95.0
DEFAULT_BRANCH_MIN = 70.0
IMPORTANT_MODULE_MINIMUMS: dict[str, float] = {
    "apply_command.py": 94.0,
    "analyze_media.py": 89.0,
    "cli_app.py": 95.0,
    "config_loader.py": 95.0,
    "gemini_client.py": 95.0,
    "logging_utils.py": 93.0,
    "manifest_store.py": 95.0,
    "pipeline_config.py": 95.0,
}

IMPORTANT_MODULE_ALIASES: dict[str, tuple[str, ...]] = {
    "cli_app.py": ("apps/cli/fileyard.py",),
}


def _is_transient_coverage_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    transient_markers = (
        "/pytest-of-",
        "/pytest-runtime/",
        "/tmp/",
        "/private/var/folders/",
    )
    return any(marker in normalized for marker in transient_markers)


def _to_percent(rate: str | None, *, context: str) -> float:
    if rate is None:
        raise ValueError(f"missing line-rate for {context}")
    value = float(rate)
    if value < 0.0 or value > 1.0:
        raise ValueError(f"line-rate out of range [0,1] for {context}: {rate}")
    return value * 100.0


def _load_file_coverages(coverage_xml: Path) -> tuple[float, float, dict[str, float]]:
    root = ET.parse(coverage_xml).getroot()
    total = _to_percent(root.attrib.get("line-rate"), context="coverage root")
    branch_total = _to_percent(root.attrib.get("branch-rate"), context="coverage root")
    files: dict[str, float] = {}
    duplicates: set[str] = set()
    for cls in root.findall(".//class"):
        filename = (cls.attrib.get("filename") or "").strip()
        if not filename:
            continue
        normalized = filename.replace("\\", "/")
        if normalized in files:
            duplicates.add(normalized)
            continue
        files[normalized] = _to_percent(
            cls.attrib.get("line-rate"),
            context=f"class {normalized}",
        )
    if duplicates:
        dup_list = ", ".join(sorted(duplicates))
        raise ValueError(f"duplicate class filename entries found in coverage xml: {dup_list}")
    return total, branch_total, files


def _resolve_file_coverage(files: dict[str, float], module: str) -> tuple[float | None, str | None]:
    alias_matches = [(alias, files[alias]) for alias in IMPORTANT_MODULE_ALIASES.get(module, ()) if alias in files]
    alias_paths = {path for path, _ in alias_matches}
    if module in files:
        return files[module], None
    normalized = module.replace("\\", "/")
    if normalized in files:
        return files[normalized], None
    basename = Path(normalized).name
    if basename in files:
        matches = [(basename, files[basename]), *alias_matches]
        non_alias_matches = [(path, value) for path, value in matches if path not in alias_paths]
        if len(non_alias_matches) == 1:
            return non_alias_matches[0][1], None
        if len(matches) == 1:
            return matches[0][1], None
        matched_files = ", ".join(sorted(k for k, _ in matches))
        return None, f"ambiguous module coverage entry: {module} matched multiple files: {matched_files}"
    matches = [(k, v) for k, v in files.items() if k.endswith("/" + basename)]
    matches.extend(alias_matches)
    deduped: dict[str, float] = {}
    for path, value in matches:
        deduped[path] = value
    matches = list(deduped.items())
    canonical_matches = [(path, value) for path, value in matches if not _is_transient_coverage_path(path)]
    if canonical_matches:
        matches = canonical_matches
    non_alias_matches = [(path, value) for path, value in matches if path not in alias_paths]
    if len(non_alias_matches) == 1:
        return non_alias_matches[0][1], None
    if len(non_alias_matches) > 1:
        matched_files = ", ".join(sorted(k for k, _ in non_alias_matches))
        return None, f"ambiguous module coverage entry: {module} matched multiple files: {matched_files}"
    if len(matches) == 1:
        return matches[0][1], None
    if len(matches) > 1:
        matched_files = ", ".join(sorted(k for k, _ in matches))
        return None, f"ambiguous module coverage entry: {module} matched multiple files: {matched_files}"
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coverage-xml",
        default=".runtime-cache/ci/coverage.xml",
        help="Path to coverage.xml",
    )
    parser.add_argument(
        "--min-total",
        type=float,
        default=DEFAULT_TOTAL_MIN,
        help=f"Minimum overall coverage percentage (default: {DEFAULT_TOTAL_MIN})",
    )
    parser.add_argument(
        "--min-branch",
        type=float,
        default=DEFAULT_BRANCH_MIN,
        help=f"Minimum overall branch coverage percentage (default: {DEFAULT_BRANCH_MIN})",
    )
    args = parser.parse_args()

    if args.min_total < 0.0 or args.min_total > 100.0:
        print(f"❌ coverage-threshold: invalid --min-total {args.min_total} (expected 0-100)")
        return 2
    if args.min_branch < 0.0 or args.min_branch > 100.0:
        print(f"❌ coverage-threshold: invalid --min-branch {args.min_branch} (expected 0-100)")
        return 2

    coverage_xml = Path(args.coverage_xml).resolve()
    if not coverage_xml.exists():
        print(f"❌ coverage-threshold: coverage xml not found: {coverage_xml}")
        return 1

    try:
        total, branch_total, files = _load_file_coverages(coverage_xml)
    except ET.ParseError as exc:
        print(f"❌ coverage-threshold: invalid xml: {coverage_xml}")
        print(f"- parse-error: {exc}")
        return 1
    except ValueError as exc:
        print(f"❌ coverage-threshold: invalid coverage data: {coverage_xml}")
        print(f"- {exc}")
        return 1

    if not files:
        print(f"❌ coverage-threshold: no file-level coverage entries found in {coverage_xml}")
        return 1

    failures: list[str] = []
    lines: list[str] = []

    if total < args.min_total:
        failures.append(f"overall coverage {total:.2f}% < required {args.min_total:.2f}%")
    lines.append(f"[{'PASS' if total >= args.min_total else 'FAIL'}] overall={total:.2f}% (required>={args.min_total:.2f}%)")
    if branch_total < args.min_branch:
        failures.append(f"overall branch coverage {branch_total:.2f}% < required {args.min_branch:.2f}%")
    lines.append(
        f"[{'PASS' if branch_total >= args.min_branch else 'FAIL'}] overall-branch={branch_total:.2f}% (required>={args.min_branch:.2f}%)"
    )

    for module, minimum in IMPORTANT_MODULE_MINIMUMS.items():
        value, error = _resolve_file_coverage(files, module)
        if value is None:
            failures.append(error or f"missing module coverage entry: {module}")
            lines.append(f"[FAIL] {module}=MISSING (required>={minimum:.2f}%)")
            continue
        if value < minimum:
            failures.append(f"{module} coverage {value:.2f}% < required {minimum:.2f}%")
        lines.append(f"[{'PASS' if value >= minimum else 'FAIL'}] {module}={value:.2f}% (required>={minimum:.2f}%)")

    if failures:
        print("❌ coverage-threshold: failed")
        for line in lines:
            print(f"- {line}")
        for msg in failures:
            print(f"- {msg}")
        return 1

    print("✅ coverage-threshold: passed")
    for line in lines:
        print(f"- {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
