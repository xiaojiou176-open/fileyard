from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tooling" / "scripts" / "check_mutation_canary.py"
    spec = importlib.util.spec_from_file_location("check_mutation_canary", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod, repo_root


def test_mutation_canary_case_catalog_is_strong_and_consistent() -> None:
    mod, repo_root = _load_module()
    cases = mod._build_cases()

    # Keep the gate broad enough to catch regressions across key modules.
    assert len(cases) >= 9

    modules = {case.module for case in cases}
    assert len(modules) == len(cases), "mutation canary modules must be unique"
    assert {
        "core_utils",
        "manifest_store",
        "config_loader",
        "apply_command",
        "pipeline_config",
        "cli_app",
        "gemini_client",
        "logging_utils",
        "analyze_media",
        "reporting",
    }.issubset(modules)

    for case in cases:
        assert case.operator
        assert case.needle != case.mutated
        assert case.tests, f"{case.module} must define at least one test"
        assert (repo_root / case.target).exists(), f"missing target for case={case.module}"
        for test_path in case.tests:
            assert (repo_root / test_path).exists(), f"missing test file for case={case.module}: {test_path}"


def test_mutation_canary_summary_fields_are_stable() -> None:
    mod, _ = _load_module()
    summary = mod._build_summary(
        [
            mod.MutationCanaryResult(module="a", operator="op_a", status="killed", message="ok"),
            mod.MutationCanaryResult(module="b", operator="op_b", status="baseline_failed", message="bad baseline"),
            mod.MutationCanaryResult(module="c", operator="op_a", status="survived", message="survived"),
        ]
    )
    assert summary["total"] == 3
    assert summary["killed"] == 1
    assert summary["baseline_failed"] == 1
    assert summary["kill_rate"] == 0.3333
    assert summary["operator_total"] == 2
    assert summary["operator_killed"] == 1
    assert summary["operator_coverage"] == 0.5


def test_mutation_canary_prefers_container_python_before_host_cache(monkeypatch) -> None:
    mod, _ = _load_module()
    monkeypatch.setenv("MOVI_IN_CONTAINER", "1")
    monkeypatch.setenv("MOVI_VENV_DIR", "/tmp/host-mounted-venv")

    candidates = mod._python_candidates()

    assert candidates[0] == Path("/opt/movi-ci-venv/bin/python")
    assert candidates[1] == Path("/tmp/host-mounted-venv/bin/python")


def test_mutation_canary_run_converts_oserror_to_completed_process(monkeypatch, tmp_path: Path) -> None:
    mod, _ = _load_module()

    def fake_run(*_args, **_kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    result = mod.run(["python", "-V"], tmp_path)

    assert result.returncode == 127
    assert result.stdout == ""
    assert "Input/output error" in result.stderr


def test_mutation_canary_run_isolates_pythonpath_and_pycache(monkeypatch, tmp_path: Path) -> None:
    mod, _ = _load_module()
    observed: dict[str, object] = {}

    def fake_run(cmd, cwd, env, text, capture_output, check):
        observed["cmd"] = cmd
        observed["cwd"] = cwd
        observed["pythonpath"] = env.get("PYTHONPATH")
        observed["pycacheprefix"] = env.get("PYTHONPYCACHEPREFIX")
        observed["pycache_exists_during_run"] = Path(env["PYTHONPYCACHEPREFIX"]).is_dir()
        observed["pytest_current_test"] = env.get("PYTEST_CURRENT_TEST")
        observed["pytest_addopts"] = env.get("PYTEST_ADDOPTS")
        observed["cov_core_source"] = env.get("COV_CORE_SOURCE")
        observed["coverage_process_start"] = env.get("COVERAGE_PROCESS_START")
        observed["tmpdir"] = env.get("TMPDIR")
        observed["tmp_exists_during_run"] = Path(env["TMPDIR"]).is_dir()
        observed["pytest_temp_root"] = env.get("PYTEST_DEBUG_TEMPROOT")
        observed["pytest_temp_root_exists_during_run"] = Path(env["PYTEST_DEBUG_TEMPROOT"]).is_dir()
        return mod.subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setenv("PYTHONPATH", "/tmp/existing-path")
    monkeypatch.setenv(
        "PYTEST_CURRENT_TEST",
        "tests/unit/test_check_mutation_canary.py::test_mutation_canary_run_isolates_pythonpath_and_pycache",
    )
    monkeypatch.setenv("PYTEST_ADDOPTS", "-q")
    monkeypatch.setenv("COV_CORE_SOURCE", "packages/application")
    monkeypatch.setenv("COVERAGE_PROCESS_START", "/tmp/.coveragerc")

    result = mod.run(["python", "-V"], tmp_path)

    assert result.returncode == 0
    assert observed["cwd"] == str(tmp_path)
    assert observed["pythonpath"] == f"{tmp_path}{os.pathsep}/tmp/existing-path"
    assert observed["pycache_exists_during_run"] is True
    assert observed["pycacheprefix"] is not None
    assert observed["tmp_exists_during_run"] is True
    assert observed["pytest_temp_root_exists_during_run"] is True
    assert observed["pytest_current_test"] is None
    assert observed["pytest_addopts"] is None
    assert observed["cov_core_source"] is None
    assert observed["coverage_process_start"] is None
    assert not Path(str(observed["pycacheprefix"])).exists()
    assert observed["tmpdir"] is not None
    assert observed["pytest_temp_root"] is not None
    assert not Path(str(observed["tmpdir"])).exists()


def test_mutation_canary_supports_json_output(tmp_path: Path, monkeypatch) -> None:
    mod, _ = _load_module()
    repo = tmp_path / "repo"
    (repo / ".runtime-cache" / "venv" / "default" / "bin").mkdir(parents=True)
    (repo / ".runtime-cache" / "venv" / "default" / "bin" / "python").write_text("#!/usr/bin/env python\n", encoding="utf-8")
    out = repo / "artifacts" / "mutation-canary.json"

    fake_case = mod.MutationCanaryCase(
        module="fake",
        operator="fake_operator",
        target="packages/domain/core_utils.py",
        needle="a",
        mutated="b",
        tests=("tests/unit/test_core_utils.py",),
    )

    monkeypatch.setattr(mod, "_build_cases", lambda: (fake_case,))
    monkeypatch.setattr(
        mod,
        "_run_case",
        lambda _repo, _py, _case: mod.MutationCanaryResult(
            module="fake",
            operator="fake_operator",
            status="killed",
            message="ok",
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_mutation_canary.py",
            "--repo-root",
            str(repo),
            "--json-output",
            str(out),
            "--json",
        ],
    )
    assert mod.main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["killed"] == 1
    assert payload["summary"]["baseline_failed"] == 0
    assert payload["summary"]["kill_rate"] == 1.0
    assert payload["summary"]["operator_total"] == 1
    assert payload["summary"]["operator_killed"] == 1
    assert payload["summary"]["operator_coverage"] == 1.0
