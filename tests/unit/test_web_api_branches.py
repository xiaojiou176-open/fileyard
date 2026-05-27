from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from test_web_api import _extract_arg, _fake_executor, _prepare_env, _read_jsonl, _wait_job

from apps.api import web_api


def _write_job_json(job_root: Path, job_id: str, payload: dict[str, Any]) -> None:
    job_dir = job_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_job_store_load_persisted_jobs_fallback_and_invalid_payloads(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)

    index_path = web_api.WEB_JOB_ROOT / "index.json"
    index_path.write_text("[]", encoding="utf-8")

    _write_job_json(
        web_api.WEB_JOB_ROOT,
        "job_ok",
        {
            "kind": "analyze",
            "status": "queued",
            "phase_label": "queued",
            "progress": 0.2,
            "created_at": "2026-01-01T00:00:00",
            "summary": {},
            "payload": {},
        },
    )
    events_path = web_api.WEB_JOB_ROOT / "job_ok" / "events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                "",
                "{bad-json",
                json.dumps({"seq": 1, "timestamp": "2026-01-01T00:00:01", "level": "info", "message": "ok", "fields": {"x": 1}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    _write_job_json(
        web_api.WEB_JOB_ROOT,
        "job_unknown_kind",
        {
            "kind": "mystery",
            "status": "queued",
            "phase_label": "queued",
            "progress": 0.1,
            "created_at": "2026-01-01T00:00:00",
            "summary": {},
            "payload": {},
        },
    )

    _write_job_json(
        web_api.WEB_JOB_ROOT,
        "job_bad_status",
        {
            "kind": "apply",
            "status": "something-weird",
            "phase_label": "queued",
            "progress": 3,
            "created_at": "2026-01-01T00:00:00",
            "summary": {},
            "payload": {},
        },
    )

    (web_api.WEB_JOB_ROOT / "job_broken").mkdir(parents=True, exist_ok=True)
    (web_api.WEB_JOB_ROOT / "job_broken" / "job.json").write_text("{", encoding="utf-8")

    store = web_api.JobStore(web_api.WEB_JOB_ROOT)
    ok = store.get("job_ok")
    assert ok is not None
    assert len(ok.events) == 1

    assert store.get("job_unknown_kind") is None
    assert store.get("job_broken") is None

    bad_status = store.get("job_bad_status")
    assert bad_status is not None
    assert bad_status.status == "failed"
    assert bad_status.progress == 1.0


def test_job_store_load_persisted_jobs_uses_index_and_skips_duplicates(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)

    index_path = web_api.WEB_JOB_ROOT / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {"id": "job_indexed"},
                    {"id": "job_indexed"},
                    {"id": "job_missing"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _write_job_json(
        web_api.WEB_JOB_ROOT,
        "job_indexed",
        {
            "kind": "rollback",
            "status": "succeeded",
            "phase_label": "succeeded",
            "progress": 1.0,
            "created_at": "2026-01-01T00:00:00",
            "summary": {},
            "payload": {},
        },
    )

    store = web_api.JobStore(web_api.WEB_JOB_ROOT)
    listed = [item.id for item in store.list()]
    assert listed.count("job_indexed") == 1
    assert store.get("job_missing") is None


def test_healthz_jobs_stream_and_not_found_routes(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)

    disconnect_counter = {"count": 0}

    async def _disconnect_after_first_loop(self: Any) -> bool:
        disconnect_counter["count"] += 1
        return disconnect_counter["count"] > 1

    monkeypatch.setattr("starlette.requests.Request.is_disconnected", _disconnect_after_first_loop)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    assert client.get("/healthz").status_code == 200
    assert client.get("/api/jobs").status_code == 200
    assert client.get("/api/jobs").json() == []

    stream_lines: list[str] = []
    with client.stream("GET", "/api/jobs/stream") as response:
        assert response.status_code == 200
        for raw_line in response.iter_lines():
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if line:
                stream_lines.append(line)
            if line == "event: snapshot":
                break
    assert "event: snapshot" in stream_lines

    assert client.get("/api/jobs/missing").status_code == 404
    assert client.get("/api/jobs/missing/events").status_code == 404
    assert client.get("/api/jobs/missing/events/stream").status_code == 404
    assert client.post("/api/jobs/missing/cancel").status_code == 404
    assert client.post("/api/jobs/missing/retry").status_code == 404
    assert client.get("/api/jobs/missing/manifest").status_code == 404
    assert client.get("/api/jobs/missing/report").status_code == 404
    assert client.get("/api/jobs/missing/audit").status_code == 404


def test_manifest_view_limit_and_validation_error_branches(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        data={"input_mode": "upload", "offline": "true"},
        files=[("files", ("a.png", b"a", "image/png")), ("files", ("b.png", b"b", "image/png"))],
    )
    assert analyze_resp.status_code == 202
    job_id = analyze_resp.json()["id"]
    _wait_job(client, job_id)

    view_resp = client.get(f"/api/jobs/{job_id}/manifest/view", params={"limit": 1})
    assert view_resp.status_code == 200
    assert view_resp.json()["returned"] == 1

    empty_patch = client.patch(f"/api/jobs/{job_id}/manifest/rows/0", json={"patch": {}})
    assert empty_patch.status_code == 400
    assert "patch cannot be empty" in empty_patch.json()["detail"]

    empty_batch = client.post(f"/api/jobs/{job_id}/manifest/batch", json={"operations": []})
    assert empty_batch.status_code == 400
    assert "operations cannot be empty" in empty_batch.json()["detail"]

    empty_resolve = client.post(f"/api/jobs/{job_id}/manifest/conflicts/resolve", json={"resolutions": []})
    assert empty_resolve.status_code == 400
    assert "resolutions cannot be empty" in empty_resolve.json()["detail"]


def test_report_and_preference_not_found_error_branches(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)
    store = app.state.job_store

    missing_report_job = store.create("analyze", {"manifest_path": str(web_api.MANIFEST_ROOT / "x.jsonl")})
    store.mark_running(missing_report_job.id)
    store.mark_succeeded(missing_report_job.id, {})
    assert client.get(f"/api/jobs/{missing_report_job.id}/report").status_code == 409

    absent_report_path = web_api.REPORT_ROOT / "no-report.json"
    absent_report_job = store.create("analyze", {"manifest_path": str(web_api.MANIFEST_ROOT / "x2.jsonl")})
    store.mark_running(absent_report_job.id)
    store.mark_succeeded(absent_report_job.id, {"report_path": str(absent_report_path)})
    assert client.get(f"/api/jobs/{absent_report_job.id}/report").status_code == 404

    assert client.delete("/api/preferences/views", params={"key": "missing"}).status_code == 404
    assert client.delete("/api/preferences/naming-templates", params={"key": "missing"}).status_code == 404


def test_retry_apply_job_builds_new_artifact_payload(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)
    store = app.state.job_store

    source = store.create(
        "apply",
        {
            "manifest_path": str(web_api.MANIFEST_ROOT / "source.jsonl"),
            "output_root": str(web_api.DEFAULT_OUTPUT_ROOT),
            "execute": False,
            "out_manifest_path": str(web_api.MANIFEST_ROOT / "old-out.jsonl"),
            "report_path": str(web_api.REPORT_ROOT / "old-report.json"),
            "rollback_manifest_path": str(web_api.ROLLBACK_ROOT / "old-rollback.jsonl"),
        },
    )
    store.mark_running(source.id)
    store.mark_succeeded(source.id, {"dry_run": True, "source_manifest_path": str(web_api.MANIFEST_ROOT / "source.jsonl")})

    retry_resp = client.post(f"/api/jobs/{source.id}/retry")
    assert retry_resp.status_code == 202
    retried = store.get(retry_resp.json()["id"])
    assert retried is not None
    assert retried.retry_of == source.id
    assert "out_manifest_path" in retried.payload
    assert "report_path" in retried.payload
    assert "rollback_manifest_path" in retried.payload
    assert retried.payload["out_manifest_path"] != source.payload["out_manifest_path"]


def test_default_command_executor_cancel_before_start_and_after_wait(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    emitted: list[tuple[str, str, dict[str, Any]]] = []

    called = {"popen": False}

    def fake_popen(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover - should not be called in first branch
        called["popen"] = True
        raise AssertionError("Popen should not run when cancelled before start")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(web_api.JobCancelled):
        web_api._default_command_executor(
            ["python", "tool.py"],
            web_api.REPO_ROOT,
            lambda level, message, fields: emitted.append((level, message, fields)),
            lambda: True,
        )
    assert called["popen"] is False
    assert any(message == "command_cancelled_before_start" for _, message, _ in emitted)

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout: Iterator[str] = iter(())

        def wait(self, timeout: float | None = None) -> int:
            return 0

    emitted.clear()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    cancel_counter = {"value": 0}

    def cancel_after_wait() -> bool:
        cancel_counter["value"] += 1
        return cancel_counter["value"] >= 2

    with pytest.raises(web_api.JobCancelled):
        web_api._default_command_executor(
            ["python", "tool.py"],
            web_api.REPO_ROOT,
            lambda level, message, fields: emitted.append((level, message, fields)),
            cancel_after_wait,
        )
    assert any(message == "command_cancelled_after_wait" for _, message, _ in emitted)


def test_static_hosting_branch_without_assets_directory(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)

    dist_dir = web_api.FRONTEND_DIST_ROOT
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html><body>index</body></html>", encoding="utf-8")
    (dist_dir / "app.js").write_text("console.log('ok')", encoding="utf-8")

    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    assert client.get("/app").status_code == 200
    assert client.get("/app/").status_code == 200
    assert client.get("/app/app.js").status_code == 200
    fallback = client.get("/app/does-not-exist")
    assert fallback.status_code == 200
    assert "index" in fallback.text
    assert client.get("/assets/app.js").status_code == 404


def test_read_preference_items_normalizes_invalid_payload(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    path = web_api.PREFERENCE_ROOT / "views.json"

    path.write_text("[]", encoding="utf-8")
    assert web_api._read_preference_items(path) == {}

    path.write_text(json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8")
    assert web_api._read_preference_items(path) == {}

    path.write_text(
        json.dumps({"items": {"valid": {"value": 1}, "invalid": "x"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert web_api._read_preference_items(path) == {"valid": {"value": 1}}


def test_job_store_event_sink_and_dry_run_branch_edges(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    store = web_api.JobStore(web_api.WEB_JOB_ROOT)

    assert store.snapshot("missing") is None

    terminal = store.create("apply", {"manifest_path": str(web_api.MANIFEST_ROOT / "terminal.jsonl")})
    store.mark_running(terminal.id)
    store.mark_succeeded(
        terminal.id,
        {"dry_run": True, "source_manifest_path": str((web_api.MANIFEST_ROOT / "terminal.jsonl").resolve())},
    )
    assert store.mark_running(terminal.id) is False

    queued_cancelled = store.create("analyze", {"manifest_path": str(web_api.MANIFEST_ROOT / "queued.jsonl")})
    queued_cancelled.cancel_requested_at = "2026-01-01T00:00:00"
    assert store.mark_running(queued_cancelled.id) is True
    assert store.get(queued_cancelled.id).status == "cancelling"  # type: ignore[union-attr]

    idempotent_cancel = store.create("analyze", {"manifest_path": str(web_api.MANIFEST_ROOT / "cancel.jsonl")})
    store.mark_cancelled(idempotent_cancel.id, "first")
    event_count = store.event_count(idempotent_cancel.id)
    store.mark_cancelled(idempotent_cancel.id, "second")
    assert store.event_count(idempotent_cancel.id) == event_count

    running_cancel = store.create("analyze", {"manifest_path": str(web_api.MANIFEST_ROOT / "run.jsonl")})
    store.mark_running(running_cancel.id)
    cancelled = store.request_cancel(running_cancel.id)
    assert cancelled is not None
    assert cancelled.status == "cancelling"

    non_dry_run = store.create("apply", {"manifest_path": str(web_api.MANIFEST_ROOT / "a.jsonl")})
    store.mark_running(non_dry_run.id)
    store.mark_succeeded(non_dry_run.id, {"dry_run": False, "source_manifest_path": ""})
    invalid_source = store.create("apply", {"manifest_path": str(web_api.MANIFEST_ROOT / "b.jsonl")})
    store.mark_running(invalid_source.id)
    store.mark_succeeded(invalid_source.id, {"dry_run": True, "source_manifest_path": "bad\0path"})
    missing_source = store.create("apply", {"manifest_path": str(web_api.MANIFEST_ROOT / "c.jsonl")})
    store.mark_running(missing_source.id)
    store.mark_succeeded(missing_source.id, {"dry_run": True, "source_manifest_path": ""})
    assert store.has_dry_run_success(web_api.MANIFEST_ROOT / "not-found.jsonl") is False

    sink = web_api.EventSink(store, running_cancel.id)
    assert sink.job_id == running_cancel.id
    sink.warn("warn_event", from_test=True)
    sink.error("error_event", from_test=True)
    messages = [event.message for event in store.get(running_cancel.id).events]  # type: ignore[union-attr]
    assert "warn_event" in messages
    assert "error_event" in messages


def test_helper_validation_and_path_resolution_errors(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)

    bad_overlay = web_api.WEB_JOB_ROOT / "bad-overlay.json"
    bad_overlay.write_text(json.dumps({"rows": []}, ensure_ascii=False), encoding="utf-8")
    payload = web_api._load_overlay(bad_overlay, "job_x")
    assert payload["rows"] == {}

    with pytest.raises(web_api.HTTPException) as non_int:
        web_api._coerce_row_index("x", 1)
    assert non_int.value.status_code == 400

    with pytest.raises(web_api.HTTPException) as out_of_range:
        web_api._coerce_row_index("2", 1)
    assert out_of_range.value.status_code == 404

    no_manifest = web_api.JobRecord(
        id="job-no-manifest",
        kind="analyze",
        status="succeeded",
        phase_label="succeeded",
        progress=1.0,
        created_at="2026-01-01T00:00:00",
        payload={},
    )
    with pytest.raises(web_api.HTTPException) as missing_manifest_field:
        web_api._get_manifest_path_for_job(no_manifest)
    assert missing_manifest_field.value.status_code == 409

    missing_file_record = web_api.JobRecord(
        id="job-missing-file",
        kind="analyze",
        status="succeeded",
        phase_label="succeeded",
        progress=1.0,
        created_at="2026-01-01T00:00:00",
        payload={"manifest_path": str(tmp_path / "missing.jsonl")},
    )
    with pytest.raises(web_api.HTTPException) as missing_manifest_file:
        web_api._get_manifest_path_for_job(missing_file_record)
    assert missing_manifest_file.value.status_code == 404


def test_apply_rollback_resolution_and_validation_branches(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)
    store = app.state.job_store

    assert client.post("/api/jobs/apply", json={"execute": False}).status_code == 400

    no_manifest_job = store.create("analyze", {"input_mode": "directory"})
    store.mark_running(no_manifest_job.id)
    store.mark_succeeded(no_manifest_job.id, {})
    assert client.post("/api/jobs/apply", json={"analyze_job_id": no_manifest_job.id, "execute": False}).status_code == 409

    missing_manifest_job = store.create("analyze", {"input_mode": "directory"})
    store.mark_running(missing_manifest_job.id)
    store.mark_succeeded(missing_manifest_job.id, {"manifest_path": str(tmp_path / "gone.jsonl")})
    assert client.post("/api/jobs/apply", json={"analyze_job_id": missing_manifest_job.id, "execute": False}).status_code == 404

    outside_dir = tmp_path / "outside-input"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_resp = client.post("/api/jobs/analyze", json={"input_mode": "directory", "input_directory": str(outside_dir)})
    assert outside_resp.status_code == 400
    assert "outside controlled roots" in outside_resp.json()["detail"] or "workspace root" in outside_resp.json()["detail"]

    inside_missing = web_api.DEFAULT_INPUT_ROOT / "missing-folder"
    missing_inside_resp = client.post("/api/jobs/analyze", json={"input_mode": "directory", "input_directory": str(inside_missing)})
    assert missing_inside_resp.status_code == 400
    assert "must exist" in missing_inside_resp.json()["detail"]

    bad_manifest = web_api.MANIFEST_ROOT / "rollback-bad.jsonl"
    bad_manifest.write_text("{bad-json", encoding="utf-8")
    bad_resp = client.post("/api/jobs/rollback", json={"manifest_path": str(bad_manifest), "execute": False})
    assert bad_resp.status_code == 409
    assert "validation failed" in bad_resp.json()["detail"]

    empty_manifest = web_api.MANIFEST_ROOT / "rollback-empty.jsonl"
    empty_manifest.write_text("", encoding="utf-8")
    empty_resp = client.post("/api/jobs/rollback", json={"manifest_path": str(empty_manifest), "execute": False})
    assert empty_resp.status_code == 409
    assert "manifest is empty" in empty_resp.json()["detail"]


def test_retry_rollback_and_manifest_context_not_found(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)
    store = app.state.job_store

    rollback_source = store.create(
        "rollback",
        {
            "manifest_path": str(web_api.MANIFEST_ROOT / "source.jsonl"),
            "execute": False,
            "allowed_root": str(web_api.DEFAULT_INPUT_ROOT.parent),
            "strict_integrity": True,
        },
    )
    store.mark_running(rollback_source.id)
    store.mark_succeeded(rollback_source.id, {"dry_run": True, "manifest_path": rollback_source.payload["manifest_path"]})
    retry_resp = client.post(f"/api/jobs/{rollback_source.id}/retry")
    assert retry_resp.status_code == 202
    retried = store.get(retry_resp.json()["id"])
    assert retried is not None
    assert retried.payload["manifest_path"] == rollback_source.payload["manifest_path"]

    missing_context = client.get("/api/jobs/not-found/manifest/view")
    assert missing_context.status_code == 404


def test_default_command_executor_empty_output_line_branch(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    emitted: list[tuple[str, str, dict[str, Any]]] = []

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = iter(["\n"])

        def wait(self, timeout: float | None = None) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    web_api._default_command_executor(
        ["python", "tool.py"],
        web_api.REPO_ROOT,
        lambda level, message, fields: emitted.append((level, message, fields)),
        lambda: False,
    )
    assert not any(message == "command_output" for _, message, _ in emitted)
    assert any(message == "command_success" for _, message, _ in emitted)


def test_job_runner_fallback_executor_and_private_run_branch(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    store = web_api.JobStore(web_api.WEB_JOB_ROOT)

    def executor_without_cancel(
        command: list[str] | tuple[str, ...],
        cwd: Path,
        emit: Any,
    ) -> None:
        emit("warn", "warn_from_executor", {})
        emit("error", "error_from_executor", {})

    runner = web_api.JobRunner(store=store, command_executor=executor_without_cancel)
    record = store.create("analyze", {"manifest_path": str(web_api.MANIFEST_ROOT / "runner.jsonl")})
    sink = web_api.EventSink(store, record.id)
    runner.run_command(["python", "tool.py"], web_api.REPO_ROOT, sink)
    messages = [event.message for event in store.get(record.id).events]  # type: ignore[union-attr]
    assert "warn_from_executor" in messages
    assert "error_from_executor" in messages

    cancelled = store.create("analyze", {"manifest_path": str(web_api.MANIFEST_ROOT / "cancelled.jsonl")})
    store.request_cancel(cancelled.id)
    runner._run(cancelled.id, lambda _: {"ok": True})  # noqa: SLF001
    assert store.get(cancelled.id).status == "cancelled"  # type: ignore[union-attr]


def test_analyze_and_apply_worker_optional_branches(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "sample.png").write_bytes(b"fake")
    captured_commands: list[list[str]] = []

    def no_report_executor(
        command: list[str] | tuple[str, ...],
        cwd: Path,
        emit: Any,
        should_cancel: Any = None,
    ) -> None:
        captured_commands.append(list(command))
        subcommand = command[2]
        if subcommand == "analyze":
            manifest = Path(_extract_arg(command, "--manifest"))
            csv = Path(_extract_arg(command, "--csv"))
            source = Path(_extract_arg(command, "--input"))
            manifest.parent.mkdir(parents=True, exist_ok=True)
            csv.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "path": str((source / "sample.png").resolve()),
                    "input_root": str(source.resolve()),
                    "media_type": "image",
                    "new_path": str((cwd / "data" / "organized" / "sample.png").resolve()),
                    "run_id": "run_custom_1",
                    "status": "pending",
                    "error_code": "",
                }
            ]
            with manifest.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            csv.write_text("path\nsample.png\n", encoding="utf-8")
            for job_dir in web_api.WEB_JOB_ROOT.iterdir():
                if job_dir.is_dir():
                    overlay = job_dir / "manifest_overlay.json"
                    overlay.write_text(
                        json.dumps(
                            {
                                "job_id": job_dir.name,
                                "updated_at": "2026-01-01T00:00:00",
                                "rows": {},
                            }
                        ),
                        encoding="utf-8",
                    )
        elif subcommand == "apply":
            source_manifest = Path(_extract_arg(command, "--manifest"))
            out_manifest = Path(_extract_arg(command, "--out-manifest"))
            rollback_manifest = Path(_extract_arg(command, "--rollback-manifest"))
            out_manifest.parent.mkdir(parents=True, exist_ok=True)
            rollback_manifest.parent.mkdir(parents=True, exist_ok=True)
            rows = _read_jsonl(source_manifest)
            with out_manifest.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(dict(row, status="applied"), ensure_ascii=False) + "\n")
            with rollback_manifest.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        emit("info", "custom_done", {"subcommand": subcommand})

    app = web_api.create_app(command_executor=no_report_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        data={"input_directory": str(raw), "model": "gemini-3-flash-preview", "offline": "false"},
    )
    assert analyze_resp.status_code == 202
    analyze_job = _wait_job(client, analyze_resp.json()["id"])
    assert analyze_job["status"] == "succeeded"
    assert analyze_job["summary"]["total"] == 0
    analyze_command = next(command for command in captured_commands if command[2] == "analyze")
    assert "--model" in analyze_command
    assert "--offline" not in analyze_command

    apply_resp = client.post("/api/jobs/apply", json={"manifest_path": analyze_job["summary"]["manifest_path"], "execute": False})
    assert apply_resp.status_code == 202
    apply_job = _wait_job(client, apply_resp.json()["id"])
    assert apply_job["status"] == "succeeded"
    assert apply_job["summary"]["total"] == 0


def test_get_manifest_limit_and_batch_partial_branches(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        data={"input_mode": "upload", "offline": "true"},
        files=[("files", ("a.png", b"a", "image/png")), ("files", ("b.png", b"b", "image/png"))],
    )
    assert analyze_resp.status_code == 202
    job_id = analyze_resp.json()["id"]
    _wait_job(client, job_id)

    manifest_limited = client.get(f"/api/jobs/{job_id}/manifest", params={"limit": 1})
    assert manifest_limited.status_code == 200
    assert manifest_limited.json()["returned"] == 1

    mixed_batch = client.post(
        f"/api/jobs/{job_id}/manifest/batch",
        json={
            "operations": [
                {"row_id": "0", "patch": {}},
                {"row_id": "0", "patch": {"not_a_field": "x"}},
            ]
        },
    )
    assert mixed_batch.status_code == 400
    assert "invalid patch fields" in mixed_batch.json()["detail"]


def test_job_store_index_jobs_shape_edge(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    index_path = web_api.WEB_JOB_ROOT / "index.json"
    index_path.write_text(json.dumps({"jobs": "not-a-list"}, ensure_ascii=False), encoding="utf-8")
    store = web_api.JobStore(web_api.WEB_JOB_ROOT)
    assert store.list() == []
