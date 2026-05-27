from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from apps.api.web_api_execution import CommandExecutionFacade, EventSink, JobCancelled, JobRunner, _default_command_executor
from apps.api.web_api_store import JobStore


def _event_messages(store: JobStore, job_id: str) -> list[str]:
    record = store.get(job_id)
    assert record is not None
    return [event.message for event in record.events]


def test_job_store_lifecycle_and_dry_run_lookup(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    manifest_path = tmp_path / "manifest.jsonl"
    manifest_path.write_text("{}", encoding="utf-8")

    created = store.create("apply", {"manifest_path": str(manifest_path)})
    assert store.get(created.id) is not None
    assert store.list()[0].id == created.id
    assert store.job_dir(created.id).exists()
    assert store.job_file(created.id).exists()
    assert store.events_file(created.id).exists()
    assert store.overlay_path(created.id).name == "manifest_overlay.json"

    assert store.mark_running(created.id) is True
    store.update_phase(created.id, "running", 0.4)
    store.add_event(created.id, "info", "midway", ok=True)
    assert store.is_cancel_requested(created.id) is False
    events, cursor, status = store.events_since(created.id, 0)
    assert cursor == len(events)
    assert status == "running"
    assert store.event_count(created.id) == len(events)

    store.mark_succeeded(created.id, {"dry_run": True, "source_manifest_path": str(manifest_path.resolve())})
    assert store.has_dry_run_success(manifest_path) is True
    snapshot = store.snapshot(created.id)
    assert snapshot is not None
    assert snapshot["status"] == "succeeded"

    failure = store.create("analyze", {"manifest_path": "x"})
    store.mark_running(failure.id)
    store.mark_failed(failure.id, "boom")
    assert store.get(failure.id).status == "failed"  # type: ignore[union-attr]

    queued = store.create("rollback", {"manifest_path": "y"})
    cancelled = store.request_cancel(queued.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"

    running = store.create("analyze", {"manifest_path": "z"})
    store.mark_running(running.id)
    cancelling = store.request_cancel(running.id)
    assert cancelling is not None
    assert cancelling.status == "cancelling"


def test_job_store_loads_persisted_jobs_and_normalizes_invalid_records(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_root.mkdir(parents=True)

    index_path = job_root / "index.json"
    index_path.write_text(json.dumps({"jobs": [{"id": "job_ok"}, {"id": "job_bad"}]}, ensure_ascii=False), encoding="utf-8")

    ok_dir = job_root / "job_ok"
    ok_dir.mkdir()
    (ok_dir / "job.json").write_text(
        json.dumps(
            {
                "kind": "analyze",
                "status": "queued",
                "phase_label": "queued",
                "progress": 0.2,
                "created_at": "2026-01-01T00:00:00Z",
                "summary": {},
                "payload": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (ok_dir / "events.jsonl").write_text(
        json.dumps({"seq": 1, "timestamp": "2026-01-01T00:00:01Z", "level": "info", "message": "ok", "fields": {}}) + "\n",
        encoding="utf-8",
    )

    bad_dir = job_root / "job_bad"
    bad_dir.mkdir()
    (bad_dir / "job.json").write_text(
        json.dumps(
            {
                "kind": "apply",
                "status": "weird-status",
                "phase_label": "queued",
                "progress": 7,
                "created_at": "2026-01-01T00:00:00Z",
                "summary": {},
                "payload": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = JobStore(job_root)
    assert store.get("job_ok") is not None
    bad_record = store.get("job_bad")
    assert bad_record is not None
    assert bad_record.status == "failed"
    assert bad_record.progress == 1.0


def test_event_sink_and_command_execution_facade_cover_both_signatures(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    record = store.create("analyze", {"manifest_path": "x"})
    sink = EventSink(store, record.id)
    assert sink.job_id == record.id

    sink.info("info_event", a=1)
    sink.warn("warn_event", a=2)
    sink.error("error_event", a=3)
    assert {"info_event", "warn_event", "error_event"}.issubset(set(_event_messages(store, record.id)))

    cancelled = {"flag": False}

    def executor_with_cancel(command: Any, cwd: Path, emit: Any, should_cancel: Any) -> None:
        emit("info", "with_cancel", {"cwd": str(cwd)})
        assert should_cancel() is False

    facade = CommandExecutionFacade(executor_with_cancel)
    assert facade.accepts_cancel is True
    facade.run(["python"], tmp_path, lambda *_: None, lambda: cancelled["flag"])

    def executor_without_cancel(command: Any, cwd: Path, emit: Any) -> None:
        emit("info", "without_cancel", {"cwd": str(cwd)})

    fallback = CommandExecutionFacade(executor_without_cancel)
    assert fallback.accepts_cancel is False
    fallback.run(["python"], tmp_path, lambda *_: None, lambda: False)


def test_job_runner_and_default_command_executor_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = JobStore(tmp_path / "jobs")

    def success_executor(command: Any, cwd: Path, emit: Any, should_cancel: Any) -> None:
        emit("info", "command_output", {"line": "ok"})

    runner = JobRunner(store, success_executor)
    record = store.create("analyze", {"manifest_path": "runner.jsonl"})
    sink = EventSink(store, record.id)
    runner.run_command(["python", "tool.py"], tmp_path, sink)
    runner._run(record.id, lambda _: {"ok": True})  # noqa: SLF001
    assert store.get(record.id).status == "succeeded"  # type: ignore[union-attr]

    cancelled = store.create("analyze", {"manifest_path": "cancel.jsonl"})
    store.request_cancel(cancelled.id)
    runner._run(cancelled.id, lambda _: {"ok": True})  # noqa: SLF001
    assert store.get(cancelled.id).status == "cancelled"  # type: ignore[union-attr]

    failed = store.create("analyze", {"manifest_path": "fail.jsonl"})
    runner._run(failed.id, lambda _: (_ for _ in ()).throw(RuntimeError("boom")))  # noqa: SLF001
    assert store.get(failed.id).status == "failed"  # type: ignore[union-attr]

    emitted: list[tuple[str, str, dict[str, Any]]] = []

    class FakeProcess:
        def __init__(self, stdout_lines: list[str], return_code: int = 0) -> None:
            self.stdout = iter(stdout_lines)
            self._return_code = return_code
            self.terminated = False
            self.killed = False

        def wait(self, timeout: float | None = None) -> int:
            return self._return_code

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

    with pytest.raises(JobCancelled):
        _default_command_executor(["python", "tool.py"], tmp_path, lambda *args: emitted.append(args), lambda: True)
    assert emitted[0][1] == "command_cancelled_before_start"

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess(["line\n"], 0))
    emitted.clear()
    _default_command_executor(["python", "tool.py"], tmp_path, lambda *args: emitted.append(args), lambda: False)
    assert any(message == "command_output" for _, message, _ in emitted)
    assert any(message == "command_success" for _, message, _ in emitted)

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess(["line\n"], 1))
    with pytest.raises(RuntimeError, match="exit code 1"):
        _default_command_executor(["python", "tool.py"], tmp_path, lambda *args: None, lambda: False)

    process = FakeProcess(["line\n"], 0)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    seen = {"count": 0}

    def _cancel_after_output() -> bool:
        seen["count"] += 1
        return seen["count"] >= 2

    with pytest.raises(JobCancelled):
        _default_command_executor(["python", "tool.py"], tmp_path, lambda *args: None, _cancel_after_output)
    assert process.terminated is True
