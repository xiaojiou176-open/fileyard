from __future__ import annotations

import json
from pathlib import Path

from tooling.scripts.generate_ci_evidence_bundle import _safe_bundle_projection, build_bundle


def _write_local_quality_gate_summary(runtime_root: Path, *, status: str = "pass") -> None:
    summary_path = runtime_root / "logs" / "quality-gate" / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "gate_run_id": "quality-gate-20260317T214626Z-97752",
                "gate_name": "quality-gate",
                "status": status,
                "execution_mode": "canonical-container",
                "summary_path": ".runtime-cache/logs/quality-gate/runs/quality-gate-20260317T214626Z-97752/summary.json",
                "latest_summary_path": ".runtime-cache/logs/quality-gate/summary.json",
                "is_canonical_signal": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_build_bundle_marks_local_bundle_as_derived_and_points_to_authoritative_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root = tmp_path / ".runtime-cache"
    _write_local_quality_gate_summary(runtime_root)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_RUN_NUMBER", raising=False)
    monkeypatch.delenv("GITHUB_WORKFLOW", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    monkeypatch.delenv("CI_NEEDS_JSON", raising=False)

    bundle = build_bundle(runtime_root)

    assert bundle["truth"]["truth_class"] == "derived-report"
    assert bundle["truth"]["source_run_type"] == "local"
    assert bundle["truth"]["authoritative_terminal_receipt"]["truth_class"] == "authoritative-terminal-receipt"
    assert bundle["truth"]["authoritative_terminal_receipt"]["path"] == ".runtime-cache/logs/quality-gate/summary.json"
    assert bundle["truth"]["authoritative_terminal_receipt"]["gate_run_id"] == "quality-gate-20260317T214626Z-97752"
    assert bundle["truth"]["remote_traceability"]["status"] == "local-only"
    assert bundle["truth"]["remote_traceability"]["has_github_run_id"] is False
    assert bundle["events"]["traceability"]["status"] == "local-only"
    assert bundle["gates"]["quality-gate"] == "pass"
    assert bundle["gates"]["details"]["quality_gate_summary_status"] == "pass"
    assert bundle["gates"]["details"]["quality_gate_is_canonical_signal"] is True


def test_build_bundle_marks_remote_current_run_when_github_run_id_is_present(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root = tmp_path / ".runtime-cache"
    _write_local_quality_gate_summary(runtime_root, status="pass")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "789")
    monkeypatch.setenv("GITHUB_WORKFLOW", "quality-gate-full")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.delenv("CI_NEEDS_JSON", raising=False)

    bundle = build_bundle(runtime_root)

    assert bundle["truth"]["source_run_type"] == "remote-current-run"
    assert bundle["truth"]["remote_traceability"]["status"] == "github-current-run-linked"
    assert bundle["truth"]["remote_traceability"]["run_id"] == "123456"
    assert bundle["events"]["traceability"]["workflow"] == "quality-gate-full"


def test_build_bundle_uses_quality_gate_pip_audit_log_for_local_security_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root = tmp_path / ".runtime-cache"
    _write_local_quality_gate_summary(runtime_root, status="fail")
    pip_audit_log = runtime_root / "logs" / "quality-gate" / "pip-audit.log"
    pip_audit_log.parent.mkdir(parents=True, exist_ok=True)
    pip_audit_log.write_text("Found 1 known vulnerability in 1 package\n", encoding="utf-8")
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("CI_NEEDS_JSON", raising=False)

    bundle = build_bundle(runtime_root)

    assert bundle["security"]["pip_audit"]["log"].endswith(".runtime-cache/logs/quality-gate/pip-audit.log")
    assert bundle["security"]["pip_audit"]["status"] == "failed"
    assert bundle["gates"]["quality-gate"] == "fail"


def test_build_bundle_treats_no_known_vulnerabilities_as_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root = tmp_path / ".runtime-cache"
    _write_local_quality_gate_summary(runtime_root, status="pass")
    pip_audit_log = runtime_root / "logs" / "quality-gate" / "pip-audit.log"
    pip_audit_log.parent.mkdir(parents=True, exist_ok=True)
    pip_audit_log.write_text("No known vulnerabilities found\n", encoding="utf-8")
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("CI_NEEDS_JSON", raising=False)

    bundle = build_bundle(runtime_root)

    assert bundle["security"]["pip_audit"]["status"] == "passed"


def test_build_bundle_exposes_plugin_scan_summary_without_report_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root = tmp_path / ".runtime-cache"
    _write_local_quality_gate_summary(runtime_root, status="pass")
    detect_report = runtime_root / "logs" / "detect-secrets-report.json"
    detect_report.parent.mkdir(parents=True, exist_ok=True)
    detect_report.write_text(json.dumps({"results": {"demo.txt": [{"type": "Secret Keyword"}]}}) + "\n", encoding="utf-8")
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("CI_NEEDS_JSON", raising=False)

    bundle = build_bundle(runtime_root)

    assert bundle["security"]["plugin_scan"]["report_present"] is True
    assert bundle["security"]["plugin_scan"]["findings"] == 1
    assert bundle["security"]["plugin_scan"]["status"] == "failed"
    assert "report" not in bundle["security"]["plugin_scan"]


def test_safe_bundle_projection_strips_scan_detail_counts() -> None:
    projection = _safe_bundle_projection(
        {
            "schema_version": "2.0",
            "gates": {
                "overall": "failed",
                "quality-gate": "fail",
                "details": {
                    "coverage_threshold": "passed",
                    "gitleaks_findings": 0,
                    "plugin_scan_findings": 2,
                },
            },
        }
    )

    assert projection["gates"]["overall"] == "failed"
    assert projection["gates"]["quality-gate"] == "fail"
    assert projection["gates"]["details"] == {"coverage_threshold": "passed"}
