from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from packages.observability.logging_utils import log_event, setup_logger
from packages.observability.run_bundle import finalize_run_bundle, initialize_run_bundle


def test_run_bundle_creates_expected_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MOVI_RUN_BUNDLE_ROOT", str(tmp_path))

    bundle = initialize_run_bundle("apply_20260314_deadbeef", "apply")
    print("stderr-line", file=sys.stderr)
    finalize_run_bundle("apply_20260314_deadbeef", "apply", "success", {"total": 3})

    summary = json.loads(Path(bundle["summary"]).read_text(encoding="utf-8"))
    evidence = json.loads(Path(bundle["evidence_index"]).read_text(encoding="utf-8"))
    stderr_text = Path(bundle["stderr"]).read_text(encoding="utf-8")

    assert summary["run_id"] == "apply_20260314_deadbeef"
    assert summary["status"] == "success"
    assert summary["total"] == 3
    assert evidence["events"] == bundle["events"]
    assert "stderr-line" in stderr_text


def test_run_bundle_logger_writes_jsonl_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MOVI_RUN_BUNDLE_ROOT", str(tmp_path))
    bundle = initialize_run_bundle("report_20260314_deadbeef", "report")

    logger = setup_logger("INFO", True)
    log_event(logger, logging.INFO, "report.generate.start", "begin", run_id="report_20260314_deadbeef")
    finalize_run_bundle("report_20260314_deadbeef", "report", "success")

    lines = Path(bundle["events"]).read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[-1])
    assert payload["event"] == "report.generate.start"
    assert payload["run_id"] == "report_20260314_deadbeef"


def test_run_bundle_records_gate_bridge_context(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MOVI_RUN_BUNDLE_ROOT", str(tmp_path))

    bundle = initialize_run_bundle(
        "report_20260314_bridge",
        "report",
        gate_run_id="quality-gate-run-1",
        gate_name="quality-gate",
    )
    finalize_run_bundle(
        "report_20260314_bridge",
        "report",
        "success",
        gate_run_id="quality-gate-run-1",
        gate_name="quality-gate",
    )

    summary = json.loads(Path(bundle["summary"]).read_text(encoding="utf-8"))
    evidence = json.loads(Path(bundle["evidence_index"]).read_text(encoding="utf-8"))

    assert summary["gate_run_id"] == "quality-gate-run-1"
    assert summary["gate_name"] == "quality-gate"
    assert evidence["gate_run_id"] == "quality-gate-run-1"
    assert evidence["gate_name"] == "quality-gate"


def test_run_bundle_reinitialization_restores_previous_stderr_handle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MOVI_RUN_BUNDLE_ROOT", str(tmp_path))

    first = initialize_run_bundle("apply_20260314_first", "apply")
    second = initialize_run_bundle("apply_20260314_second", "apply")
    print("second-stderr-line", file=sys.stderr)
    finalize_run_bundle("apply_20260314_second", "apply", "success")

    first_stderr = Path(first["stderr"]).read_text(encoding="utf-8")
    second_stderr = Path(second["stderr"]).read_text(encoding="utf-8")

    assert "second-stderr-line" not in first_stderr
    assert "second-stderr-line" in second_stderr


def test_finalize_run_bundle_recovers_from_invalid_existing_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MOVI_RUN_BUNDLE_ROOT", str(tmp_path))

    for run_id, broken_payload in (
        ("apply_20260314_empty", ""),
        ("apply_20260314_invalid", "{not-json"),
        ("apply_20260314_array", "[]"),
    ):
        bundle = initialize_run_bundle(run_id, "apply")
        summary_path = Path(bundle["summary"])
        summary_path.write_text(broken_payload, encoding="utf-8")

        finalize_run_bundle(run_id, "apply", "success", {"total": 1})

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["run_id"] == run_id
        assert summary["status"] == "success"
        assert summary["total"] == 1
