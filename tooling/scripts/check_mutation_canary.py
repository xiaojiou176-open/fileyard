#!/usr/bin/env python3
"""Mutation canary gate for pre-commit/pre-push and quality_gate fail-fast paths."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for key in list(env):
        if key.startswith("COV_CORE_") or key.startswith("COVERAGE_"):
            env.pop(key, None)
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("PYTEST_ADDOPTS", None)
    existing_pythonpath = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = f"{cwd}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(cwd)
    pycache_dir = Path(tempfile.mkdtemp(prefix="mutation-canary-pyc-"))
    runtime_tmp_dir = Path(tempfile.mkdtemp(prefix="mutation-canary-tmp-"))
    pytest_temp_root = runtime_tmp_dir / "pytest-temp"
    pytest_temp_root.mkdir(parents=True, exist_ok=True)
    env["PYTHONPYCACHEPREFIX"] = str(pycache_dir)
    env["TMPDIR"] = str(runtime_tmp_dir)
    env["TMP"] = str(runtime_tmp_dir)
    env["TEMP"] = str(runtime_tmp_dir)
    env["PYTEST_DEBUG_TEMPROOT"] = str(pytest_temp_root)
    try:
        return subprocess.run(cmd, cwd=str(cwd), env=env, text=True, capture_output=True, check=False)
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", f"{type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(runtime_tmp_dir, ignore_errors=True)
        shutil.rmtree(pycache_dir, ignore_errors=True)


def _python_candidates() -> list[Path]:
    candidates: list[Path] = []
    if os.environ.get("FILEMAN_IN_CONTAINER", "").strip() == "1":
        candidates.append(Path("/opt/fileman-ci-venv/bin/python"))
    env_venv = os.environ.get("FILEMAN_VENV_DIR", "").strip()
    if env_venv:
        candidates.append(Path(env_venv).expanduser() / "bin" / "python")
    candidates.append(Path.home() / ".cache" / "fileman" / "venv" / "default" / "bin" / "python")
    candidates.append(Path(sys.executable).resolve())

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        expanded = candidate.expanduser()
        if expanded in seen:
            continue
        deduped.append(expanded)
        seen.add(expanded)
    return deduped


def _resolve_python(repo: Path) -> Path:
    candidates = _python_candidates()

    for candidate in candidates:
        if not candidate.exists():
            continue
        probe = run([str(candidate), "-c", "import pytest"], repo)
        if probe.returncode == 0:
            return candidate
    return Path(sys.executable).resolve()


@dataclass(frozen=True)
class MutationCanaryCase:
    module: str
    operator: str
    target: str
    needle: str
    mutated: str
    tests: tuple[str, ...]


@dataclass(frozen=True)
class MutationCanaryResult:
    module: str
    operator: str
    status: str
    message: str

    @property
    def ok(self) -> bool:
        return self.status == "killed"


def _build_cases() -> tuple[MutationCanaryCase, ...]:
    return (
        MutationCanaryCase(
            module="core_utils",
            operator="boundary_truncation_guard",
            target="packages/domain/core_utils.py",
            needle='return text[: max_chars - 3] + "..."',
            mutated="return text[:max_chars]",
            tests=(
                "tests/unit/test_core_utils.py",
                "tests/unit/test_core_utils_more.py",
            ),
        ),
        MutationCanaryCase(
            module="manifest_store",
            operator="status_default_guard",
            target="packages/infrastructure/manifest_store.py",
            needle="if KEY_STATUS not in row:\n        row[KEY_STATUS] = RowStatus.PENDING.value",
            mutated="if KEY_STATUS not in row:\n        row[KEY_STATUS] = RowStatus.ERROR.value",
            tests=(
                "tests/unit/test_manifest_metadata.py",
                "tests/unit/test_manifest_store.py",
                "tests/unit/test_manifest_store_more.py",
            ),
        ),
        MutationCanaryCase(
            module="config_loader",
            operator="type_validation_guard",
            target="packages/infrastructure/config_loader.py",
            needle='if not isinstance(data, dict):\n        raise RuntimeError("JSON top-level value must be an object")',
            mutated='if isinstance(data, dict):\n        raise RuntimeError("JSON top-level value must be an object")',
            tests=(
                "tests/unit/test_config_loader.py",
                "tests/unit/test_config_loader_validate.py",
                "tests/unit/test_config_loader_strict_validation.py",
            ),
        ),
        MutationCanaryCase(
            module="apply_command",
            operator="membership_filter_guard",
            target="packages/application/apply_command.py",
            needle=(
                "if status_val in {RowStatus.APPLIED.value, RowStatus.DUPLICATE.value}:\n"
                "                    item[_ROLLBACK_SIG_KEY] = _sign_rollback_record(item, run_id)"
            ),
            mutated=(
                "if status_val not in {RowStatus.APPLIED.value, RowStatus.DUPLICATE.value}:\n"
                "                    item[_ROLLBACK_SIG_KEY] = _sign_rollback_record(item, run_id)"
            ),
            tests=(
                "tests/unit/test_apply_changes_wal_recovery_edges.py",
                "tests/unit/test_apply_changes.py",
                "tests/unit/test_apply_integrity_security.py",
                "tests/unit/test_apply_changes_resume_and_root_guard.py",
            ),
        ),
        MutationCanaryCase(
            module="pipeline_config",
            operator="constant_mapping_guard",
            target="packages/domain/pipeline_config.py",
            needle="if mode == Durability.SYNC:\n        return 1",
            mutated="if mode == Durability.SYNC:\n        return 0",
            tests=("tests/unit/test_pipeline_config_durability.py",),
        ),
        MutationCanaryCase(
            module="cli_app",
            operator="boolean_composition_guard",
            target="apps/cli/cli_app.py",
            needle='return os.environ.get("FILEMAN_ENABLE_TEST_HOOKS", "") == "1" or bool(os.environ.get("PYTEST_CURRENT_TEST", ""))',
            mutated='return os.environ.get("FILEMAN_ENABLE_TEST_HOOKS", "") == "1" and bool(os.environ.get("PYTEST_CURRENT_TEST", ""))',
            tests=("tests/unit/test_cli_app.py",),
        ),
        MutationCanaryCase(
            module="gemini_client",
            operator="empty_response_guard",
            target="packages/infrastructure/gemini_client.py",
            needle='if not raw:\n        raise ValueError("empty response")',
            mutated='if raw:\n        raise ValueError("empty response")',
            tests=(
                "tests/unit/test_gemini_client_parse.py",
                "tests/unit/test_gemini_client_more.py",
            ),
        ),
        MutationCanaryCase(
            module="logging_utils",
            operator="security_redaction_guard",
            target="packages/observability/logging_utils.py",
            needle="return bool(_SENSITIVE_KEY_PATTERN.search(key.lower()))",
            mutated="return False",
            tests=("tests/unit/test_logging_utils.py",),
        ),
        MutationCanaryCase(
            module="analyze_media",
            operator="shape_validation_guard",
            target="packages/application/analyze_media_helpers.py",
            needle='if not isinstance(ai, dict):\n        return {}, ["AI output must be an object"]',
            mutated='if isinstance(ai, dict):\n        return {}, ["AI output must be an object"]',
            tests=(
                "tests/unit/test_analyze_media_sanitize.py",
                "tests/unit/test_analyze_media_confidence_and_timeout.py",
            ),
        ),
        MutationCanaryCase(
            module="reporting",
            operator="error_accounting_guard",
            target="packages/application/reporting.py",
            needle="if row.get(KEY_ERROR):\n            self.with_error += 1",
            mutated="if not row.get(KEY_ERROR):\n            self.with_error += 1",
            tests=("tests/unit/test_reporting.py",),
        ),
    )


def _pytest_cmd(py: Path, tests: tuple[str, ...]) -> list[str]:
    return [str(py), "-m", "pytest", "-q", "-o", "addopts=", *tests]


def _purge_target_pyc(target: Path) -> None:
    cache_dir = target.parent / "__pycache__"
    if not cache_dir.exists():
        return
    stem = target.stem
    for pyc in cache_dir.glob(f"{stem}*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            continue


def _run_case(repo: Path, py: Path, case: MutationCanaryCase) -> MutationCanaryResult:
    target = repo / case.target
    if not target.exists():
        return MutationCanaryResult(
            module=case.module,
            operator=case.operator,
            status="setup_failed",
            message=f"❌ mutation_canary[{case.module}]: missing target file: {target}",
        )

    if not case.tests:
        return MutationCanaryResult(
            module=case.module,
            operator=case.operator,
            status="setup_failed",
            message=f"❌ mutation_canary[{case.module}]: case.tests must not be empty",
        )

    missing_tests = [str(repo / test_path) for test_path in case.tests if not (repo / test_path).exists()]
    if missing_tests:
        return MutationCanaryResult(
            module=case.module,
            operator=case.operator,
            status="setup_failed",
            message=(f"❌ mutation_canary[{case.module}]: missing test file(s) in case.tests: " + ", ".join(missing_tests)),
        )

    _purge_target_pyc(target)
    baseline = run(_pytest_cmd(py, case.tests), repo)
    if baseline.returncode != 0:
        return MutationCanaryResult(
            module=case.module,
            operator=case.operator,
            status="baseline_failed",
            message=(f"❌ mutation_canary[{case.module}]: baseline tests must pass before mutation\n{baseline.stdout}{baseline.stderr}"),
        )

    src = target.read_text(encoding="utf-8")
    if case.needle not in src:
        return MutationCanaryResult(
            module=case.module,
            operator=case.operator,
            status="setup_failed",
            message=f"❌ mutation_canary[{case.module}]: expected canary line not found, update script",
        )

    try:
        target.write_text(src.replace(case.needle, case.mutated, 1), encoding="utf-8")
        _purge_target_pyc(target)
        mutated_run = run(_pytest_cmd(py, case.tests), repo)
    finally:
        target.write_text(src, encoding="utf-8")
        _purge_target_pyc(target)

    if mutated_run.returncode == 0:
        return MutationCanaryResult(
            module=case.module,
            operator=case.operator,
            status="survived",
            message=(
                f"❌ mutation_canary[{case.module}]: "
                "mutated code did not break tests (false green risk)\n"
                f"{mutated_run.stdout}{mutated_run.stderr}"
            ),
        )
    return MutationCanaryResult(
        module=case.module,
        operator=case.operator,
        status="killed",
        message=f"✅ mutation_canary[{case.module}]: mutation killed by tests",
    )


def _build_summary(results: list[MutationCanaryResult]) -> dict[str, float | int | dict[str, dict[str, int]]]:
    total = len(results)
    killed = sum(1 for item in results if item.status == "killed")
    baseline_failed = sum(1 for item in results if item.status == "baseline_failed")
    kill_rate = (killed / total) if total else 0.0
    operator_map: dict[str, dict[str, int]] = {}
    for item in results:
        bucket = operator_map.setdefault(item.operator, {"killed": 0, "survived": 0, "baseline_failed": 0, "setup_failed": 0})
        if item.status in bucket:
            bucket[item.status] += 1
    operator_total = len(operator_map)
    operator_killed = sum(1 for status_map in operator_map.values() if status_map.get("killed", 0) > 0)
    operator_coverage = (operator_killed / operator_total) if operator_total else 0.0
    return {
        "total": total,
        "killed": killed,
        "baseline_failed": baseline_failed,
        "kill_rate": round(kill_rate, 4),
        "operator_total": operator_total,
        "operator_killed": operator_killed,
        "operator_coverage": round(operator_coverage, 4),
        "operators": operator_map,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Mutation canary gate: mutate a core branch and require tests to fail.")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary to stdout")
    parser.add_argument(
        "--json-output",
        default="",
        help="Write machine-readable JSON report to file path",
    )
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    py = _resolve_python(repo)
    if not py.exists():
        print(f"❌ mutation_canary: missing venv python: {py}")
        return 2
    cases = _build_cases()
    results: list[MutationCanaryResult] = []
    for case in cases:
        result = _run_case(repo, py, case)
        results.append(result)
        print(result.message)

    summary = _build_summary(results)
    summary_line = (
        "mutation_canary summary: "
        f"total={summary['total']} "
        f"killed={summary['killed']} "
        f"baseline_failed={summary['baseline_failed']} "
        f"kill_rate={summary['kill_rate']:.2%} "
        f"operator_coverage={summary['operator_coverage']:.2%} "
        f"operators={summary['operator_killed']}/{summary['operator_total']}"
    )
    print(summary_line)
    if summary["killed"] == summary["total"]:
        print(f"✅ mutation_canary: all {len(cases)} module canaries were killed")

    report = {
        "summary": summary,
        "results": [{"module": item.module, "operator": item.operator, "status": item.status, "message": item.message} for item in results],
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.json_output:
        output_path = Path(args.json_output)
        if not output_path.is_absolute():
            output_path = repo / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return 0 if summary["killed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
