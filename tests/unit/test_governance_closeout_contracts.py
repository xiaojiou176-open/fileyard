from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False, env=env)


def test_positioning_claims_gate_rejects_forbidden_phrase(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "governance").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    (repo / "contracts" / "governance" / "project_positioning.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "claim_surfaces:",
                "  - path: README.md",
                "    required_snippets:",
                '      - "有限维护开源"',
                "  - path: docs/open_source_runbook.md",
                "    required_snippets:",
                '      - "bash tooling/gates/platform_alignment_gate.sh"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "public_claims_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "forbidden_phrases:",
                '  - "fully green"',
                "claim_surfaces:",
                "  - path: README.md",
                "    required_snippets:",
                '      - "平台态闭环请运行：`bash tooling/gates/platform_alignment_gate.sh`"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "有限维护开源\n平台态闭环请运行：`bash tooling/gates/platform_alignment_gate.sh`\nfully green\n",
        encoding="utf-8",
    )
    (repo / "docs" / "open_source_runbook.md").write_text(
        "bash tooling/gates/platform_alignment_gate.sh\n",
        encoding="utf-8",
    )

    proc = _run([sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_positioning_claims.py"), "--root", str(repo)], repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "forbidden stale/overclaim phrase present" in out


def test_hotspot_budget_gate_rejects_non_test_shim_importer(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "governance").mkdir(parents=True)
    (repo / "packages" / "application").mkdir(parents=True)
    (repo / "apps" / "demo").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "contracts" / "governance" / "hotspot_budget.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "hotspots:",
                "  - path: packages/application/apply_command.py",
                "    max_lines: 10",
                "shim_guards:",
                "  - shim_path: packages/application/apply_changes.py",
                "    module_name: packages.application.apply_changes",
                "    allowed_importer_prefixes:",
                "      - tests/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "packages" / "application" / "apply_command.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "packages" / "application" / "apply_changes.py").write_text("def cmd_apply():\n    return None\n", encoding="utf-8")
    (repo / "apps" / "demo" / "bad.py").write_text(
        "from packages.application import apply_changes\n",
        encoding="utf-8",
    )

    proc = _run([sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_hotspot_budget.py"), "--root", str(repo)], repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "forbidden non-test import of shim module" in out


def test_hotspot_budget_collect_python_files_falls_back_when_rglob_is_volatile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    (repo / "packages" / "application").mkdir(parents=True)
    (repo / ".runtime-cache" / "tmp").mkdir(parents=True)
    (repo / ".agents").mkdir(parents=True)
    (repo / "packages" / "application" / "keep.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / ".runtime-cache" / "tmp" / "skip.py").write_text("print('skip')\n", encoding="utf-8")
    (repo / ".agents" / "skip.py").write_text("print('skip')\n", encoding="utf-8")

    script_path = REPO_ROOT / "tooling" / "scripts" / "check_hotspot_budget.py"
    spec = importlib.util.spec_from_file_location("check_hotspot_budget_module", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def _boom(self: Path, pattern: str):  # type: ignore[override]
        raise FileNotFoundError("transient runtime tmp disappeared")

    monkeypatch.setattr(Path, "rglob", _boom)

    files = module._collect_python_files(repo)
    relative_files = {path.relative_to(repo).as_posix() for path in files}
    assert "packages/application/keep.py" in relative_files
    assert ".runtime-cache/tmp/skip.py" not in relative_files
    assert ".agents/skip.py" not in relative_files


def test_remote_required_checks_gate_matches_policy_with_fake_gh(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (repo / "contracts" / "governance").mkdir(parents=True)
    (repo / "contracts" / "governance" / "required_checks_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "workflow_file: .github/workflows/ci.yml",
                "branch_protection_target: main",
                "required_checks:",
                "  - job_id: quality-gate-full",
                "    blocking_level: required",
                "  - job_id: packaging-gate",
                "    blocking_level: required",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "public_readiness_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "default_branch: main",
                "release_mode:",
                "  require_public_repo: true",
                "  require_pvr: true",
                "  require_branch_protection: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gh = bin_dir / "gh"
    gh.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "repo" ] && [ "$2" = "view" ]; then',
                '  printf \'%s\\n\' \'{"nameWithOwner":"demo/repo","isPrivate":false,"defaultBranchRef":{"name":"main"}}\'',
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/private-vulnerability-reporting" ]; then',
                "  printf '%s\\n' '{\"enabled\":true}'",
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/branches/main/protection" ]; then',
                (
                    "  printf '%s%s\\n' "
                    '\'{"required_status_checks":{"checks":[{"context":"quality-gate-full"},\' '
                    '\'{"context":"packaging-gate"}]}}\''
                ),
                "  exit 0",
                "fi",
                'echo "unsupported gh args: $*" >&2',
                "exit 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

    proc = _run(
        [sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_remote_required_checks.py"), "--root", str(repo)],
        repo,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_gate_log_correlation_gate_validates_summary_and_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "runtime").mkdir(parents=True)
    (repo / ".runtime-cache" / "logs" / "quality-gate").mkdir(parents=True)
    (repo / ".runtime-cache" / "logs" / "platform-alignment").mkdir(parents=True)
    (repo / "contracts" / "runtime" / "gate_log_schema.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "required_gates:",
                "  - gate_name: quality-gate",
                "    summary_path: .runtime-cache/logs/quality-gate/summary.json",
                "    bridge_log_step_name: logging-contract",
                "    bridge_required_event_fields:",
                "      - gate_run_id",
                "      - gate_name",
                "  - gate_name: platform-alignment",
                "    summary_path: .runtime-cache/logs/platform-alignment/summary.json",
                "required_top_level_fields:",
                "  - gate_run_id",
                "  - gate_name",
                "  - status",
                "  - started_at",
                "  - ended_at",
                "  - duration_ms",
                "  - steps",
                "required_step_fields:",
                "  - step_name",
                "  - status",
                "  - started_at",
                "  - ended_at",
                "  - duration_ms",
                "  - artifact_log_path",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    for gate_name in ("quality-gate", "platform-alignment"):
        log_dir = repo / ".runtime-cache" / "logs" / gate_name
        (log_dir / "step.log").write_text("ok\n", encoding="utf-8")
        step_name = "logging-contract" if gate_name == "quality-gate" else "demo-step"
        if gate_name == "quality-gate":
            (log_dir / "step.log").write_text(
                "\n".join(
                    [
                        '{"event":"report.generate.start","gate_run_id":"quality-gate-1","gate_name":"quality-gate"}',
                        '{"event":"report.generate.fail","gate_run_id":"quality-gate-1","gate_name":"quality-gate"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        (log_dir / "summary.json").write_text(
            "{\n"
            f'  "gate_run_id": "{gate_name}-1",\n'
            f'  "gate_name": "{gate_name}",\n'
            '  "status": "pass",\n'
            '  "started_at": "2026-03-16T13:00:00Z",\n'
            '  "ended_at": "2026-03-16T13:00:01Z",\n'
            '  "duration_ms": 1000,\n'
            '  "steps": [\n'
            "    {\n"
            f'      "step_name": "{step_name}",\n'
            '      "status": "pass",\n'
            '      "started_at": "2026-03-16T13:00:00Z",\n'
            '      "ended_at": "2026-03-16T13:00:01Z",\n'
            '      "duration_ms": 1000,\n'
            f'      "artifact_log_path": ".runtime-cache/logs/{gate_name}/step.log"\n'
            "    }\n"
            "  ]\n"
            "}\n",
            encoding="utf-8",
        )

    proc = _run([sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_gate_log_correlation.py"), "--root", str(repo)], repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_gate_log_correlation_can_target_single_gate_with_custom_summary_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "runtime").mkdir(parents=True)
    (repo / ".runtime-cache" / "logs" / "quality-gate" / "runs" / "quality-gate-host-1").mkdir(parents=True)
    (repo / "contracts" / "runtime" / "gate_log_schema.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "required_gates:",
                "  - gate_name: quality-gate",
                "    summary_path: .runtime-cache/logs/quality-gate/summary.json",
                "    bridge_log_step_name: logging-contract",
                "    bridge_required_event_fields:",
                "      - gate_run_id",
                "      - gate_name",
                "  - gate_name: platform-alignment",
                "    summary_path: .runtime-cache/logs/platform-alignment/summary.json",
                "required_top_level_fields:",
                "  - gate_run_id",
                "  - gate_name",
                "  - status",
                "  - started_at",
                "  - ended_at",
                "  - duration_ms",
                "  - steps",
                "required_step_fields:",
                "  - step_name",
                "  - status",
                "  - started_at",
                "  - ended_at",
                "  - duration_ms",
                "  - artifact_log_path",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    run_dir = repo / ".runtime-cache" / "logs" / "quality-gate" / "runs" / "quality-gate-host-1"
    (run_dir / "preflight-checks.log").write_text("ok\n", encoding="utf-8")
    (run_dir / "logging-contract.log").write_text(
        "\n".join(
            [
                '{"event":"report.generate.start","gate_run_id":"quality-gate-host-1","gate_name":"quality-gate"}',
                '{"event":"report.generate.fail","gate_run_id":"quality-gate-host-1","gate_name":"quality-gate"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / ".step-summary.jsonl").write_text(
        (
            '{"step_name":"preflight-checks","status":"fail","started_at":"2026-03-16T13:00:00Z","ended_at":"2026-03-16T13:00:01Z","duration_ms":1000,"artifact_log_path":".runtime-cache/logs/quality-gate/runs/quality-gate-host-1/preflight-checks.log"}\n'
            '{"step_name":"logging-contract","status":"pass","started_at":"2026-03-16T13:00:00Z","ended_at":"2026-03-16T13:00:01Z","duration_ms":1000,"artifact_log_path":".runtime-cache/logs/quality-gate/runs/quality-gate-host-1/logging-contract.log"}\n'
        ),
        encoding="utf-8",
    )
    (repo / ".runtime-cache" / "logs" / "quality-gate" / ".host-step-summary.jsonl").write_text(
        (run_dir / ".step-summary.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo / ".runtime-cache" / "logs" / "quality-gate" / "host-summary.json").write_text(
        "{\n"
        '  "gate_run_id": "quality-gate-host-1",\n'
        '  "gate_name": "quality-gate",\n'
        '  "status": "fail",\n'
        '  "started_at": "2026-03-16T13:00:00Z",\n'
        '  "ended_at": "2026-03-16T13:00:01Z",\n'
        '  "duration_ms": 1000,\n'
        '  "execution_mode": "host-emergency",\n'
        '  "receipt_dir": ".runtime-cache/logs/quality-gate/runs/quality-gate-host-1",\n'
        '  "summary_path": ".runtime-cache/logs/quality-gate/host-summary.json",\n'
        '  "step_summary_path": ".runtime-cache/logs/quality-gate/runs/quality-gate-host-1/.step-summary.jsonl",\n'
        '  "latest_summary_path": ".runtime-cache/logs/quality-gate/host-summary.json",\n'
        '  "latest_step_summary_path": ".runtime-cache/logs/quality-gate/.host-step-summary.jsonl",\n'
        '  "is_canonical_signal": false,\n'
        '  "steps": [\n'
        "    {\n"
        '      "step_name": "preflight-checks",\n'
        '      "status": "fail",\n'
        '      "started_at": "2026-03-16T13:00:00Z",\n'
        '      "ended_at": "2026-03-16T13:00:01Z",\n'
        '      "duration_ms": 1000,\n'
        '      "artifact_log_path": ".runtime-cache/logs/quality-gate/runs/quality-gate-host-1/preflight-checks.log"\n'
        "    },\n"
        "    {\n"
        '      "step_name": "logging-contract",\n'
        '      "status": "pass",\n'
        '      "started_at": "2026-03-16T13:00:00Z",\n'
        '      "ended_at": "2026-03-16T13:00:01Z",\n'
        '      "duration_ms": 1000,\n'
        '      "artifact_log_path": ".runtime-cache/logs/quality-gate/runs/quality-gate-host-1/logging-contract.log"\n'
        "    }\n"
        "  ]\n"
        "}\n",
        encoding="utf-8",
    )

    proc = _run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_gate_log_correlation.py"),
            "--root",
            str(repo),
            "--gate",
            "quality-gate",
            "--summary-path",
            ".runtime-cache/logs/quality-gate/host-summary.json",
        ],
        repo,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_quality_gate_receipts_separate_canonical_and_host_latest_aliases() -> None:
    script = (REPO_ROOT / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")

    assert 'LATEST_SUMMARY_REL_PATH="$ARTIFACT_LOGS_REL/summary.json"' in script
    assert 'LATEST_SUMMARY_REL_PATH="$ARTIFACT_LOGS_REL/host-summary.json"' in script
    assert 'LATEST_STEP_SUMMARY_REL_PATH="$ARTIFACT_LOGS_REL/.step-summary.jsonl"' in script
    assert 'LATEST_STEP_SUMMARY_REL_PATH="$ARTIFACT_LOGS_REL/.host-step-summary.jsonl"' in script
    assert 'RUN_ARTIFACT_REL_DIR="$ARTIFACT_LOGS_REL/runs/$GATE_RUN_ID"' in script
    assert '"execution_mode": sys.argv[9]' in script
    assert '"receipt_dir": sys.argv[10]' in script
    assert '"is_canonical_signal": sys.argv[15] == "1"' in script
    assert 'QUALITY_GATE_FORCED_RUN_ID="$GATE_RUN_ID"' in script
    assert "resolve_receipt_python()" in script
    assert 'if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -V >/dev/null 2>&1; then' in script
    assert "command -v python3" in script
    assert "run_receipt_python()" in script
    assert 'run_receipt_python - "$RUN_STEP_SUMMARY_PATH"' in script
    assert 'run_receipt_python - "$RUN_STEP_SUMMARY_PATH" "$RUN_SUMMARY_PATH"' in script
    assert 'record_step_summary "container-bootstrap" "fail"' in script
    assert "write_gate_summary fail" in script
