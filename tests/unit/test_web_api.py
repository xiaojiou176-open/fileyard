from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Sequence

import pytest
from fastapi.testclient import TestClient

from apps.api import web_api, web_api_store


def _extract_arg(command: Sequence[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fake_executor(
    command: Sequence[str],
    cwd: Path,
    emit: Callable[[str, str, dict[str, Any]], None],
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    if should_cancel and should_cancel():
        raise web_api.JobCancelled("cancel requested before fake executor")

    emit("info", "fake_command_start", {"command": " ".join(command), "cwd": str(cwd)})
    subcommand = command[2]

    if subcommand == "analyze":
        manifest = Path(_extract_arg(command, "--manifest"))
        report = Path(_extract_arg(command, "--report"))
        csv = Path(_extract_arg(command, "--csv"))
        input_root = Path(_extract_arg(command, "--input"))

        manifest.parent.mkdir(parents=True, exist_ok=True)
        report.parent.mkdir(parents=True, exist_ok=True)
        csv.parent.mkdir(parents=True, exist_ok=True)

        files = sorted([path for path in input_root.iterdir() if path.is_file()]) if input_root.exists() else []
        if not files:
            files = [input_root / "sample.png"]

        rows: list[dict[str, Any]] = []
        for idx, file_path in enumerate(files, start=1):
            rows.append(
                {
                    "path": str(file_path.resolve()),
                    "input_root": str(input_root.resolve()),
                    "media_type": "image",
                    "sha1": ("a" * 38) + f"{idx:02d}",
                    "hash8": f"aaaaaa{idx:02d}"[:8],
                    "file_mtime": "2026-01-01T00:00:00",
                    "run_id": f"run_web_api_{idx}",
                    "ai": {
                        "kind": "截图",
                        "category": "工作",
                        "title": f"测试样例-{idx}",
                        "tags": ["test"],
                        "confidence": 0.9,
                    },
                    "new_path": str((cwd / "data" / "organized" / file_path.name).resolve()),
                    "status": "pending",
                    "error_code": "",
                }
            )

        with manifest.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        report.write_text(
            json.dumps(
                {
                    "total": len(rows),
                    "with_error": 0,
                    "by_media_type": {"image": len(rows)},
                    "by_kind": {"截图": len(rows)},
                    "by_category": {"工作": len(rows)},
                    "by_status": {"pending": len(rows)},
                    "error_codes": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        csv.write_text("path,ai_kind\n" + "\n".join([f"{Path(row['path']).name},截图" for row in rows]) + "\n", encoding="utf-8")

    elif subcommand == "apply":
        manifest_in = Path(_extract_arg(command, "--manifest"))
        out_manifest = Path(_extract_arg(command, "--out-manifest"))
        report = Path(_extract_arg(command, "--report"))
        rollback_manifest = Path(_extract_arg(command, "--rollback-manifest"))

        out_manifest.parent.mkdir(parents=True, exist_ok=True)
        report.parent.mkdir(parents=True, exist_ok=True)
        rollback_manifest.parent.mkdir(parents=True, exist_ok=True)

        source_rows = _read_jsonl(manifest_in)
        updated_rows = []
        for row in source_rows:
            updated = dict(row)
            updated["status"] = "applied"
            updated["error_code"] = ""
            updated_rows.append(updated)

        with out_manifest.open("w", encoding="utf-8") as handle:
            for row in updated_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        with rollback_manifest.open("w", encoding="utf-8") as handle:
            for row in updated_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        report.write_text(json.dumps({"total": len(updated_rows), "with_error": 0}, ensure_ascii=False), encoding="utf-8")

    elif subcommand == "rollback":
        # rollback dry-run path in unit tests does not need extra files.
        pass

    else:  # pragma: no cover - guard
        raise RuntimeError(f"unexpected command: {command}")

    if should_cancel and should_cancel():
        raise web_api.JobCancelled("cancel requested after fake executor")

    emit("info", "fake_command_done", {"subcommand": subcommand})


def _slow_cancel_executor(
    command: Sequence[str],
    cwd: Path,
    emit: Callable[[str, str, dict[str, Any]], None],
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    for _ in range(50):
        if should_cancel and should_cancel():
            raise web_api.JobCancelled("cancel requested in slow executor")
        time.sleep(0.01)
    _fake_executor(command, cwd, emit, should_cancel)


def _wait_job(client: TestClient, job_id: str, timeout_s: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in web_api.TERMINAL_JOB_STATUSES:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"job timeout: {job_id}")


def _prepare_env(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    artifacts = workspace / ".movi" / "artifacts"
    manifests = workspace / ".movi" / "manifests"
    input_root = workspace / "data" / "raw"
    output_root = workspace / "data" / "organized"
    cli_entrypoint = repo / "apps" / "cli" / "fileyard.py"
    frontend_dist = repo / ".runtime-cache" / "apps" / "webui" / "build"
    cli_entrypoint.parent.mkdir(parents=True, exist_ok=True)
    cli_entrypoint.write_text("# test fixture entrypoint\n", encoding="utf-8")
    input_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)
    (artifacts / "report").mkdir(parents=True, exist_ok=True)
    (artifacts / "rollback").mkdir(parents=True, exist_ok=True)
    (artifacts / "web_api" / "jobs").mkdir(parents=True, exist_ok=True)
    (artifacts / "web_api" / "uploads").mkdir(parents=True, exist_ok=True)
    (artifacts / "web_api" / "preferences").mkdir(parents=True, exist_ok=True)
    (workspace / ".movi" / "preferences").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(web_api, "REPO_ROOT", repo)
    monkeypatch.setattr(web_api, "CLI_ENTRYPOINT", cli_entrypoint)
    monkeypatch.setattr(web_api, "WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(web_api, "WEB_ARTIFACT_ROOT", artifacts / "web_api")
    monkeypatch.setattr(web_api, "WEB_JOB_ROOT", artifacts / "web_api" / "jobs")
    monkeypatch.setattr(web_api, "WEB_UPLOAD_ROOT", artifacts / "web_api" / "uploads")
    monkeypatch.setattr(web_api, "PREFERENCE_ROOT", workspace / ".movi" / "preferences")
    monkeypatch.setattr(web_api, "MANIFEST_ROOT", manifests)
    monkeypatch.setattr(web_api, "REPORT_ROOT", artifacts / "report")
    monkeypatch.setattr(web_api, "ROLLBACK_ROOT", artifacts / "rollback")
    monkeypatch.setattr(web_api, "DEFAULT_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(web_api, "DEFAULT_INPUT_ROOT", input_root)
    monkeypatch.setattr(web_api, "DEFAULT_ALLOWED_ROOT", f"{input_root},{output_root}")
    monkeypatch.setattr(web_api, "FRONTEND_DIST_ROOT", frontend_dist)
    monkeypatch.setenv("MOVI_ROLLBACK_HMAC_KEY", "unit-test-web-api-hmac-key")


def test_analyze_directory_and_read_manifest_report(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")

    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    resp = client.post(
        "/api/jobs/analyze",
        json={
            "input_mode": "directory",
            "input_directory": str(raw),
            "offline": True,
        },
    )
    assert resp.status_code == 202
    job_id = resp.json()["id"]
    finished = _wait_job(client, job_id)
    assert finished["status"] == "succeeded"
    assert finished["summary"]["total"] == 1
    assert Path(finished["summary"]["overlay_path"]).exists()

    manifest_resp = client.get(f"/api/jobs/{job_id}/manifest")
    assert manifest_resp.status_code == 200
    assert manifest_resp.json()["returned"] == 1

    report_resp = client.get(f"/api/jobs/{job_id}/report")
    assert report_resp.status_code == 200
    assert report_resp.json()["report"]["total"] == 1
    assert report_resp.json()["report"]["review_copilot_summary"]["guardrails"]["execute_allowed"] is False
    assert report_resp.json()["report"]["review_bridge"]["review_queue_path"] == f"/api/jobs/{job_id}/review-queue"
    assert report_resp.json()["report"]["review_bridge"]["execute_allowed"] is False

    events_resp = client.get(f"/api/jobs/{job_id}/events")
    assert events_resp.status_code == 200
    assert events_resp.json()["events"]


def test_analyze_directory_stays_within_timeout_under_slow_job_persistence(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")

    original_write_json_atomic = web_api_store._write_json_atomic

    def slow_write_json_atomic(path: Path, payload: Any, *, root: Path) -> None:
        time.sleep(0.45)
        original_write_json_atomic(path, payload, root=root)

    monkeypatch.setattr(web_api_store, "_write_json_atomic", slow_write_json_atomic)

    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    resp = client.post(
        "/api/jobs/analyze",
        json={
            "input_mode": "directory",
            "input_directory": str(raw),
            "offline": True,
        },
    )
    assert resp.status_code == 202

    finished = _wait_job(client, resp.json()["id"], timeout_s=6.0)
    assert finished["status"] == "succeeded"


def test_analyze_directory_rejects_outside_controlled_root(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    resp = client.post(
        "/api/jobs/analyze",
        json={
            "input_mode": "directory",
            "input_directory": str(outside),
            "offline": True,
        },
    )
    assert resp.status_code == 400
    assert "outside controlled roots" in resp.text or "workspace root" in resp.text


def test_analyze_upload_mode(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    resp = client.post(
        "/api/jobs/analyze",
        data={"input_mode": "upload", "offline": "true"},
        files=[("files", ("a.png", b"img-a", "image/png")), ("files", ("b.png", b"img-b", "image/png"))],
    )
    assert resp.status_code == 202
    job_id = resp.json()["id"]
    finished = _wait_job(client, job_id)
    assert finished["status"] == "succeeded"
    assert finished["summary"]["input_mode"] == "upload"
    assert finished["summary"]["total"] == 2


def test_apply_job_rejects_output_root_outside_controlled_root(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")

    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        json={
            "input_mode": "directory",
            "input_directory": str(raw),
            "offline": True,
        },
    )
    job_id = analyze_resp.json()["id"]
    _wait_job(client, job_id)

    resp = client.post(
        "/api/jobs/apply",
        json={
            "analyze_job_id": job_id,
            "execute": False,
            "output_root": str(tmp_path / "outside-output"),
        },
    )
    assert resp.status_code == 400
    assert "outside controlled roots" in resp.text or "workspace root" in resp.text


def test_analyze_upload_mode_preserves_relative_paths(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    resp = client.post(
        "/api/jobs/analyze",
        data={
            "input_mode": "upload",
            "offline": "true",
            "relative_paths": ["Trips/Seattle/a.png", "Trips/Seattle/b.png"],
        },
        files=[("files", ("a.png", b"img-a", "image/png")), ("files", ("b.png", b"img-b", "image/png"))],
    )
    assert resp.status_code == 202
    job_id = resp.json()["id"]
    finished = _wait_job(client, job_id)
    upload_root = Path(finished["summary"]["input_root"])
    assert (upload_root / "Trips" / "Seattle" / "a.png").exists()
    assert (upload_root / "Trips" / "Seattle" / "b.png").exists()


def test_apply_job_uses_upload_input_root_from_analyze_summary(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    captured_commands: list[list[str]] = []

    def recording_executor(
        command: Sequence[str],
        cwd: Path,
        emit: Callable[[str, str, dict[str, Any]], None],
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        captured_commands.append(list(command))
        _fake_executor(command, cwd, emit, should_cancel)

    app = web_api.create_app(command_executor=recording_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        data={
            "input_mode": "upload",
            "offline": "true",
            "relative_paths": ["Trips/Seattle/a.png", "Trips/Seattle/b.png"],
        },
        files=[("files", ("a.png", b"img-a", "image/png")), ("files", ("b.png", b"img-b", "image/png"))],
    )
    assert analyze_resp.status_code == 202
    analyze_job_id = analyze_resp.json()["id"]
    analyze_done = _wait_job(client, analyze_job_id)
    expected_input_root = str(Path(analyze_done["summary"]["input_root"]).resolve())

    apply_resp = client.post(
        "/api/jobs/apply",
        json={"analyze_job_id": analyze_job_id, "execute": False},
    )
    assert apply_resp.status_code == 202
    apply_done = _wait_job(client, apply_resp.json()["id"])
    assert apply_done["status"] == "succeeded"

    apply_commands = [command for command in captured_commands if len(command) >= 3 and command[2] == "apply"]
    assert apply_commands
    apply_command = apply_commands[-1]
    assert _extract_arg(apply_command, "--input-root") == expected_input_root


def test_apply_job_rejects_analyze_summary_input_root_outside_controlled_roots(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        json={"input_mode": "directory", "input_directory": str(web_api.DEFAULT_INPUT_ROOT), "offline": True},
    )
    assert analyze_resp.status_code == 202
    analyze_job_id = analyze_resp.json()["id"]
    analyze_done = _wait_job(client, analyze_job_id)
    assert analyze_done["status"] == "succeeded"

    store = app.state.job_store
    record = store.get(analyze_job_id)
    assert record is not None
    summary = dict(record.summary)
    summary["input_root"] = str((tmp_path / "outside-root").resolve())
    record.summary = summary
    with store._lock:
        store._jobs[analyze_job_id] = record
        store._write_job_locked(record)
        store._write_index_locked()

    apply_resp = client.post("/api/jobs/apply", json={"analyze_job_id": analyze_job_id, "execute": False})
    assert apply_resp.status_code == 202
    apply_done = _wait_job(client, apply_resp.json()["id"])
    assert apply_done["status"] == "failed"
    latest_error = str(apply_done["latest_error"]).lower()
    assert "outside controlled roots" in latest_error or "workspace root" in latest_error or "input directory must exist" in latest_error


def test_apply_job_uses_watch_source_input_root_for_inbox_analyze_jobs(monkeypatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    captured_commands: list[list[str]] = []

    def capturing_executor(
        command: Sequence[str],
        cwd: Path,
        emit: Callable[[str, str, dict[str, Any]], None],
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        captured_commands.append(list(command))
        _fake_executor(command, cwd, emit, should_cancel)

    app = web_api.create_app(command_executor=capturing_executor)
    client = TestClient(app)

    source_root = tmp_path / "watch-source"
    source_root.mkdir()
    (source_root / "note.txt").write_text("hello", encoding="utf-8")

    watch_resp = client.post(
        "/api/preferences/watch-sources",
        json={"name": "Inbox", "input_root": str(source_root), "enabled": True},
    )
    assert watch_resp.status_code == 200

    inbox_resp = client.post("/api/inbox/scan")
    assert inbox_resp.status_code == 200

    analyze_resp = client.post(
        "/api/inbox/analyze",
        json={"watch_source_id": watch_resp.json()["id"], "batch_id": inbox_resp.json()["items"][0]["id"], "offline": True},
    )
    assert analyze_resp.status_code == 202
    analyze_job_id = analyze_resp.json()["job_id"]
    _wait_job(client, analyze_job_id)

    apply_resp = client.post("/api/jobs/apply", json={"analyze_job_id": analyze_job_id, "execute": False})
    assert apply_resp.status_code == 202
    apply_done = _wait_job(client, apply_resp.json()["id"])
    assert apply_done["status"] == "succeeded"

    apply_command = next(command for command in captured_commands if len(command) >= 3 and command[2] == "apply")
    assert _extract_arg(apply_command, "--input-root") == str(source_root.resolve())


def test_watch_source_rejects_filesystem_root(monkeypatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    resp = client.post(
        "/api/preferences/watch-sources",
        json={"name": "Inbox", "input_root": "/", "enabled": True},
    )
    assert resp.status_code == 400
    assert "filesystem root" in resp.json()["detail"].lower()


def test_resolve_existing_operator_directory_returns_absolute_path_without_resolve(monkeypatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    relative_root = Path("data/raw")
    monkeypatch.chdir(web_api.WORKSPACE_ROOT)

    resolved = web_api._resolve_existing_operator_directory(relative_root, field_name="input_root")

    assert resolved == (web_api.WORKSPACE_ROOT / relative_root).absolute()


def test_normalize_operator_directory_input_allows_missing_path_without_filesystem_touch(monkeypatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    relative_root = Path("data/future-inbox")
    monkeypatch.chdir(web_api.WORKSPACE_ROOT)

    normalized = web_api._normalize_operator_directory_input(relative_root, field_name="input_root")

    assert normalized == (web_api.WORKSPACE_ROOT / relative_root).absolute()


def test_report_endpoint_rejects_report_path_outside_report_root(monkeypatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")
    resp = client.post("/api/jobs/analyze", json={"input_mode": "directory", "input_directory": str(raw), "offline": True})
    assert resp.status_code == 202
    job_id = resp.json()["id"]
    _wait_job(client, job_id)

    store = app.state.job_store
    record = store.get(job_id)
    assert record is not None
    summary = dict(record.summary)
    summary["report_path"] = str((tmp_path / "outside-report.json").resolve())
    record.summary = summary
    with store._lock:
        store._jobs[job_id] = record
        store._write_job_locked(record)
        store._write_index_locked()

    report_resp = client.get(f"/api/jobs/{job_id}/report")
    assert report_resp.status_code == 400
    assert "outside controlled roots" in report_resp.json()["detail"].lower()


def test_frontend_route_blocks_path_escape(monkeypatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    frontend_dist = web_api.FRONTEND_DIST_ROOT
    frontend_dist.mkdir(parents=True, exist_ok=True)
    (frontend_dist / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    resp = client.get("/app/%2e%2e/%2e%2e/etc/passwd")
    assert resp.status_code == 200
    assert "ok" in resp.text


def test_analyze_forwards_workers_categories_and_limits(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")
    captured_commands: list[list[str]] = []

    def capturing_executor(
        command: Sequence[str],
        cwd: Path,
        emit: Callable[[str, str, dict[str, Any]], None],
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        captured_commands.append(list(command))
        _fake_executor(command, cwd, emit, should_cancel)

    app = web_api.create_app(command_executor=capturing_executor)
    client = TestClient(app)

    resp = client.post(
        "/api/jobs/analyze",
        json={
            "input_mode": "directory",
            "input_directory": str(raw),
            "offline": True,
            "model": "gemini-3-flash-preview",
            "categories": "travel,family",
            "workers": 3,
            "max_files": 200,
            "max_total_mb": 512.5,
            "max_file_mb": 24.0,
        },
    )
    assert resp.status_code == 202
    _wait_job(client, resp.json()["id"])
    analyze_command = next(command for command in captured_commands if command[2] == "analyze")
    assert analyze_command[analyze_command.index("--workers") + 1] == "3"
    assert analyze_command[analyze_command.index("--categories") + 1] == "travel,family"
    assert analyze_command[analyze_command.index("--max-files") + 1] == "200"
    assert analyze_command[analyze_command.index("--max-total-mb") + 1] == "512.5"
    assert analyze_command[analyze_command.index("--max-file-mb") + 1] == "24.0"


def test_runtime_settings_roundtrip(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    initial = client.get("/api/preferences/runtime")
    assert initial.status_code == 200
    assert initial.json()["ready"] is False
    assert "GEMINI_API_KEY" in initial.json()["missing"]

    new_input = web_api.WORKSPACE_ROOT / "photo-source"
    new_output = web_api.WORKSPACE_ROOT / "photo-output"
    updated = client.post(
        "/api/preferences/runtime",
        json={
            "api_key": "live-key-for-runtime-roundtrip-12345",
            "model": "gemini-3-flash-preview",
            "input_root": str(new_input),
            "output_root": str(new_output),
            "create_missing_dirs": True,
        },
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["ready"] is True
    assert payload["input_root"] == str(new_input.resolve())
    assert payload["output_root"] == str(new_output.resolve())
    assert new_input.exists()
    assert new_output.exists()

    env_path = Path(payload["runtime_env_path"])
    rendered = env_path.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=live-key-for-runtime-roundtrip-12345" in rendered
    assert f"MOVI_INPUT_ROOT={new_input.resolve()}" in rendered
    assert f"MOVI_OUTPUT_ROOT={new_output.resolve()}" in rendered

    validated = client.post("/api/preferences/runtime/validate")
    assert validated.status_code == 200
    assert validated.json()["ready"] is True


def test_runtime_settings_reject_workspace_escape_segments(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    escaped_input = f"{web_api.WORKSPACE_ROOT}/../outside-root"
    resp = client.post(
        "/api/preferences/runtime",
        json={
            "input_root": escaped_input,
            "output_root": str((web_api.WORKSPACE_ROOT / "photo-output").resolve()),
            "create_missing_dirs": False,
        },
    )

    assert resp.status_code == 400
    assert "outside controlled roots" in resp.json()["detail"].lower() or "workspace root" in resp.json()["detail"].lower()


def test_apply_execute_requires_previous_dry_run(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        json={"input_mode": "directory", "input_directory": str(raw), "offline": True},
    )
    analyze_id = analyze_resp.json()["id"]
    _wait_job(client, analyze_id)

    blocked = client.post("/api/jobs/apply", json={"analyze_job_id": analyze_id, "execute": True})
    assert blocked.status_code == 409

    dry_run = client.post("/api/jobs/apply", json={"analyze_job_id": analyze_id, "execute": False})
    assert dry_run.status_code == 202
    dry_job = _wait_job(client, dry_run.json()["id"])
    assert dry_job["status"] == "succeeded"
    assert dry_job["summary"]["dry_run"] is True

    execute_resp = client.post("/api/jobs/apply", json={"analyze_job_id": analyze_id, "execute": True})
    assert execute_resp.status_code == 202
    exec_job = _wait_job(client, execute_resp.json()["id"])
    assert exec_job["status"] == "succeeded"
    assert exec_job["summary"]["dry_run"] is False


def test_rollback_requires_manifest_with_run_id(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    bad_manifest = web_api.MANIFEST_ROOT / "bad.jsonl"
    bad_manifest.write_text(
        json.dumps(
            {
                "path": str((web_api.DEFAULT_INPUT_ROOT / "x.png").resolve()),
                "new_path": str((web_api.DEFAULT_OUTPUT_ROOT / "x.png").resolve()),
                "media_type": "image",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    blocked = client.post("/api/jobs/rollback", json={"manifest_path": str(bad_manifest), "execute": True})
    assert blocked.status_code == 409

    good_manifest = web_api.MANIFEST_ROOT / "good.jsonl"
    good_manifest.write_text(
        json.dumps(
            {
                "path": str((web_api.DEFAULT_INPUT_ROOT / "x.png").resolve()),
                "new_path": str((web_api.DEFAULT_OUTPUT_ROOT / "x.png").resolve()),
                "media_type": "image",
                "run_id": "run_ok_1",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    accepted = client.post("/api/jobs/rollback", json={"manifest_path": str(good_manifest), "execute": False})
    assert accepted.status_code == 202
    done = _wait_job(client, accepted.json()["id"])
    assert done["status"] == "succeeded"


def test_job_stream_sse_snapshot_and_done(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")

    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        json={"input_mode": "directory", "input_directory": str(raw), "offline": True},
    )
    job_id = analyze_resp.json()["id"]
    _wait_job(client, job_id)

    collected: list[str] = []
    with client.stream("GET", f"/api/jobs/{job_id}/events/stream") as response:
        assert response.status_code == 200
        for raw_line in response.iter_lines():
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if line:
                collected.append(line)
            if line == "event: done":
                break

    assert "event: snapshot" in collected
    assert "event: done" in collected
    assert any(line.startswith("data: ") for line in collected)


def test_preview_endpoint(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")

    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        json={"input_mode": "directory", "input_directory": str(raw), "offline": True},
    )
    job_id = analyze_resp.json()["id"]
    _wait_job(client, job_id)

    preview_resp = client.get(f"/api/jobs/{job_id}/manifest/0/preview")
    assert preview_resp.status_code == 200
    payload = preview_resp.json()
    assert payload["row_id"] == "0"
    assert payload["media_type"] == "image"
    assert "summary" in payload


def test_cancel_and_retry(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")

    app = web_api.create_app(command_executor=_slow_cancel_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        json={"input_mode": "directory", "input_directory": str(raw), "offline": True},
    )
    original_job_id = analyze_resp.json()["id"]

    cancel_resp = client.post(f"/api/jobs/{original_job_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] in {"cancelling", "cancelled"}

    cancelled = _wait_job(client, original_job_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_requested_at"]

    retry_resp = client.post(f"/api/jobs/{original_job_id}/retry")
    assert retry_resp.status_code == 202
    retried_job_id = retry_resp.json()["id"]
    retried = _wait_job(client, retried_job_id)
    assert retried["status"] == "succeeded"
    assert retried["retry_of"] == original_job_id


def test_retry_requires_terminal_status(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")

    app = web_api.create_app(command_executor=_slow_cancel_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        json={"input_mode": "directory", "input_directory": str(raw), "offline": True},
    )
    job_id = analyze_resp.json()["id"]

    retry_resp = client.post(f"/api/jobs/{job_id}/retry")
    assert retry_resp.status_code == 409
    assert retry_resp.json()["detail"] == "only terminal jobs can be retried"

    # Cleanup in-flight background task to keep the test deterministic.
    client.post(f"/api/jobs/{job_id}/cancel")
    _wait_job(client, job_id)


def test_manifest_overlay_sidecar_conflict_and_resolve(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "a.png").write_bytes(b"a")
    (raw / "b.png").write_bytes(b"b")

    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        json={"input_mode": "directory", "input_directory": str(raw), "offline": True},
    )
    analyze_job_id = analyze_resp.json()["id"]
    finished = _wait_job(client, analyze_job_id)

    manifest_path = Path(finished["summary"]["manifest_path"])
    original_rows = _read_jsonl(manifest_path)
    assert len(original_rows) == 2

    conflict_path = str((web_api.DEFAULT_OUTPUT_ROOT / "conflict.png").resolve())

    patched = client.patch(
        f"/api/jobs/{analyze_job_id}/manifest/rows/0",
        json={"patch": {"new_path": conflict_path}},
    )
    assert patched.status_code == 200

    batched = client.post(
        f"/api/jobs/{analyze_job_id}/manifest/batch",
        json={"operations": [{"row_id": "1", "patch": {"new_path": conflict_path}}]},
    )
    assert batched.status_code == 200

    conflicts = client.get(f"/api/jobs/{analyze_job_id}/manifest/conflicts")
    assert conflicts.status_code == 200
    assert conflicts.json()["count"] == 2

    resolve = client.post(
        f"/api/jobs/{analyze_job_id}/manifest/conflicts/resolve",
        json={
            "resolutions": [
                {
                    "row_id": "1",
                    "new_path": str((web_api.DEFAULT_OUTPUT_ROOT / "resolved-b.png").resolve()),
                }
            ]
        },
    )
    assert resolve.status_code == 200
    assert resolve.json()["remaining_count"] == 0

    view = client.get(f"/api/jobs/{analyze_job_id}/manifest/view")
    assert view.status_code == 200
    assert view.json()["returned"] == 2


def test_manifest_patch_allows_new_path_even_when_missing_from_base_row(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "a.png").write_bytes(b"a")

    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        json={"input_mode": "directory", "input_directory": str(raw), "offline": True},
    )
    analyze_job_id = analyze_resp.json()["id"]
    finished = _wait_job(client, analyze_job_id)

    manifest_path = Path(finished["summary"]["manifest_path"])
    rows = _read_jsonl(manifest_path)
    original_rows = [dict(row) for row in rows]
    rows[0].pop("new_path", None)
    with manifest_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    patched = client.post(
        f"/api/jobs/{analyze_job_id}/manifest/batch",
        json={
            "operations": [
                {
                    "row_id": "0",
                    "patch": {
                        "new_path": str((web_api.DEFAULT_OUTPUT_ROOT / "patched.png").resolve()),
                    },
                }
            ]
        },
    )
    assert patched.status_code == 200
    returned_rows = patched.json()["rows"]
    assert returned_rows[0]["new_path"].endswith("patched.png")

    overlay_path = web_api.WEB_JOB_ROOT / analyze_job_id / "manifest_overlay.json"
    assert overlay_path.exists()
    overlay_payload = json.loads(overlay_path.read_text(encoding="utf-8"))
    assert set(overlay_payload["rows"].keys()) == {"0"}

    # Overlay sidecar must not mutate source manifest.
    post_rows = _read_jsonl(manifest_path)
    assert post_rows == rows
    assert post_rows != original_rows


def test_manifest_overlay_patch_rejects_invalid_field(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")

    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        json={"input_mode": "directory", "input_directory": str(raw), "offline": True},
    )
    analyze_job_id = analyze_resp.json()["id"]
    _wait_job(client, analyze_job_id)

    invalid_patch = client.patch(
        f"/api/jobs/{analyze_job_id}/manifest/rows/0",
        json={"patch": {"not_a_manifest_field": "x"}},
    )
    assert invalid_patch.status_code == 400
    assert "invalid patch fields" in invalid_patch.json()["detail"]


def test_apply_uses_resolved_manifest_snapshot(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")

    apply_manifests: list[str] = []

    def recording_executor(
        command: Sequence[str],
        cwd: Path,
        emit: Callable[[str, str, dict[str, Any]], None],
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        if command[2] == "apply":
            apply_manifests.append(_extract_arg(command, "--manifest"))
        _fake_executor(command, cwd, emit, should_cancel)

    app = web_api.create_app(command_executor=recording_executor)
    client = TestClient(app)

    analyze_resp = client.post(
        "/api/jobs/analyze",
        json={"input_mode": "directory", "input_directory": str(raw), "offline": True},
    )
    analyze_job_id = analyze_resp.json()["id"]
    analyze_done = _wait_job(client, analyze_job_id)

    source_manifest_path = Path(analyze_done["summary"]["manifest_path"])
    source_rows = _read_jsonl(source_manifest_path)
    original_new_path = source_rows[0]["new_path"]

    patched_new_path = str((web_api.DEFAULT_OUTPUT_ROOT / "patched-v2.png").resolve())
    patch_resp = client.patch(
        f"/api/jobs/{analyze_job_id}/manifest/rows/0",
        json={"patch": {"new_path": patched_new_path}},
    )
    assert patch_resp.status_code == 200

    apply_resp = client.post(
        "/api/jobs/apply",
        json={"analyze_job_id": analyze_job_id, "execute": False},
    )
    assert apply_resp.status_code == 202
    apply_done = _wait_job(client, apply_resp.json()["id"])
    assert apply_done["status"] == "succeeded"

    summary = apply_done["summary"]
    resolved_manifest_path = Path(summary["resolved_manifest_path"])
    assert resolved_manifest_path.exists()

    resolved_rows = _read_jsonl(resolved_manifest_path)
    assert resolved_rows[0]["new_path"] == patched_new_path

    assert apply_manifests
    assert Path(apply_manifests[-1]).resolve() == resolved_manifest_path.resolve()

    # Source manifest remains unchanged.
    latest_source_rows = _read_jsonl(source_manifest_path)
    assert latest_source_rows[0]["new_path"] == original_new_path


def test_history_restore(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")

    app1 = web_api.create_app(command_executor=_fake_executor)
    client1 = TestClient(app1)

    analyze_resp = client1.post(
        "/api/jobs/analyze",
        json={"input_mode": "directory", "input_directory": str(raw), "offline": True},
    )
    job_id = analyze_resp.json()["id"]
    _wait_job(client1, job_id)

    # Restart app and ensure persisted history is restored from the workspace artifact index.
    app2 = web_api.create_app(command_executor=_fake_executor)
    client2 = TestClient(app2)
    history_resp = client2.get("/api/jobs/history")
    assert history_resp.status_code == 200
    payload = history_resp.json()
    ids = [item["id"] for item in payload["items"]]
    assert job_id in ids


def test_saved_views_and_naming_templates(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    save_view = client.post(
        "/api/preferences/views",
        json={"key": "default-grid", "value": {"columns": ["path", "new_path"], "sort": "path"}},
    )
    assert save_view.status_code == 200

    list_views = client.get("/api/preferences/views")
    assert list_views.status_code == 200
    assert list_views.json()["count"] == 1

    delete_view = client.delete("/api/preferences/views", params={"key": "default-grid"})
    assert delete_view.status_code == 200

    save_template = client.post(
        "/api/preferences/naming-templates",
        json={"key": "cn-media", "value": {"template": "{category}/{title}_{hash8}"}},
    )
    assert save_template.status_code == 200

    list_templates = client.get("/api/preferences/naming-templates")
    assert list_templates.status_code == 200
    assert list_templates.json()["count"] == 1

    delete_template = client.delete("/api/preferences/naming-templates", params={"key": "cn-media"})
    assert delete_template.status_code == 200


def test_rollback_audit(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    good_manifest = web_api.MANIFEST_ROOT / "rollback-ready.jsonl"
    good_manifest.write_text(
        json.dumps(
            {
                "path": str((web_api.DEFAULT_INPUT_ROOT / "x.png").resolve()),
                "new_path": str((web_api.DEFAULT_OUTPUT_ROOT / "x.png").resolve()),
                "media_type": "image",
                "run_id": "run_ok_2",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rollback_resp = client.post("/api/jobs/rollback", json={"manifest_path": str(good_manifest), "execute": False})
    assert rollback_resp.status_code == 202
    rollback_job = _wait_job(client, rollback_resp.json()["id"])
    assert rollback_job["status"] == "succeeded"

    audit_resp = client.get(f"/api/jobs/{rollback_resp.json()['id']}/audit")
    assert audit_resp.status_code == 200
    audit_payload = audit_resp.json()
    assert audit_payload["job"]["status"] == "succeeded"
    assert audit_payload["event_count"] > 0
    assert audit_payload["summary"]["dry_run"] is True

    paths = audit_payload["paths"]
    assert Path(paths["job_json_path"]).exists()
    assert Path(paths["events_jsonl_path"]).exists()
    assert Path(paths["index_path"]).exists()

    tail_resp = client.get(f"/api/jobs/{rollback_resp.json()['id']}/audit", params={"tail": 1})
    assert tail_resp.status_code == 200
    assert len(tail_resp.json()["events_tail"]) == 1


def test_rollback_accepts_webui_fields(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    good_manifest = web_api.MANIFEST_ROOT / "rollback-webui.jsonl"
    good_manifest.write_text(
        json.dumps(
            {
                "path": str((web_api.DEFAULT_INPUT_ROOT / "x.png").resolve()),
                "new_path": str((web_api.DEFAULT_OUTPUT_ROOT / "x.png").resolve()),
                "media_type": "image",
                "run_id": "run_webui_rollback",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rollback_resp = client.post(
        "/api/jobs/rollback",
        json={
            "manifest_path": str(good_manifest),
            "execute": False,
            "source_job_id": "job_source_1",
            "allowed_root": str(web_api.DEFAULT_INPUT_ROOT.parent),
            "strict_integrity": False,
            "audit_reason": "webui smoke",
        },
    )
    assert rollback_resp.status_code == 202
    rollback_job = _wait_job(client, rollback_resp.json()["id"])
    assert rollback_job["status"] == "succeeded"
    assert rollback_job["summary"]["allowed_root"] == str(web_api.DEFAULT_INPUT_ROOT.parent)
    assert rollback_job["summary"]["strict_integrity"] is False
    assert rollback_job["summary"]["audit_reason"] == "webui smoke"


def test_rollback_strict_integrity_missing_key_fails_before_enqueue(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    monkeypatch.delenv("MOVI_ROLLBACK_HMAC_KEY", raising=False)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    good_manifest = web_api.MANIFEST_ROOT / "rollback-strict-missing-key.jsonl"
    good_manifest.write_text(
        json.dumps(
            {
                "path": str((web_api.DEFAULT_INPUT_ROOT / "x.png").resolve()),
                "new_path": str((web_api.DEFAULT_OUTPUT_ROOT / "x.png").resolve()),
                "media_type": "image",
                "run_id": "run_webui_rollback_missing_key",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    jobs_before = len(client.get("/api/jobs").json())
    rollback_resp = client.post(
        "/api/jobs/rollback",
        json={
            "manifest_path": str(good_manifest),
            "execute": False,
            "strict_integrity": True,
        },
    )
    assert rollback_resp.status_code == 400
    assert rollback_resp.json()["detail"] == "strict_integrity=true requires MOVI_ROLLBACK_HMAC_KEY"
    assert len(client.get("/api/jobs").json()) == jobs_before


def test_rollback_non_strict_emits_integrity_relaxed_warning(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    monkeypatch.delenv("MOVI_ROLLBACK_HMAC_KEY", raising=False)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    good_manifest = web_api.MANIFEST_ROOT / "rollback-nonstrict-warning.jsonl"
    good_manifest.write_text(
        json.dumps(
            {
                "path": str((web_api.DEFAULT_INPUT_ROOT / "x.png").resolve()),
                "new_path": str((web_api.DEFAULT_OUTPUT_ROOT / "x.png").resolve()),
                "media_type": "image",
                "run_id": "run_webui_rollback_relaxed",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rollback_resp = client.post(
        "/api/jobs/rollback",
        json={
            "manifest_path": str(good_manifest),
            "execute": False,
            "strict_integrity": False,
        },
    )
    assert rollback_resp.status_code == 202
    job_id = rollback_resp.json()["id"]
    rollback_job = _wait_job(client, job_id)
    assert rollback_job["status"] == "succeeded"
    events = client.get(f"/api/jobs/{job_id}/events").json()["events"]
    assert any(event["message"] == "rollback_integrity_relaxed" for event in events)


def test_web_api_helper_utilities_and_store_edges(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)

    root = web_api.DEFAULT_INPUT_ROOT.parent
    inside = root / "raw" / "sample.txt"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("ok", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("no", encoding="utf-8")

    assert web_api._within_root(inside, root) is True
    assert web_api._within_root(outside, root) is False
    assert web_api._sanitize_filename("", 7) == "upload-0007.bin"
    assert web_api._sanitize_filename("../demo.png", 1) == "demo.png"
    assert web_api._safe_float_progress(-1) == 0.0
    assert web_api._safe_float_progress(2) == 1.0
    assert web_api._safe_float_progress(0.12345) == 0.1235
    assert web_api._parse_form_bool("yes") is True
    assert web_api._parse_form_bool(True) is True
    assert web_api._parse_form_bool("OFF", default=True) is False
    assert web_api._parse_form_bool("unknown", default=True) is True

    overlay_path = web_api.WEB_JOB_ROOT / "job_test" / "manifest_overlay.json"
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_text("[]", encoding="utf-8")
    overlay = web_api._load_overlay(overlay_path, "job_test")
    assert overlay["job_id"] == "job_test"
    assert overlay["rows"] == {}

    saved = web_api._save_overlay(overlay_path, "job_test", {"0": {"new_path": "x"}})
    assert saved["rows"]["0"]["new_path"] == "x"
    assert json.loads(overlay_path.read_text(encoding="utf-8"))["rows"]["0"]["new_path"] == "x"

    overlay_rows: dict[str, Any] = {
        "0": {"status": "done"},
        "bad": {"status": "skip"},
        "9": {"status": "skip"},
        "1": "bad-patch",
    }
    merged = web_api._apply_overlay_rows(
        [{"new_path": "a", "status": "pending"}, {"new_path": "b", "status": "pending"}],
        overlay_rows,
    )
    assert merged[0]["status"] == "done"
    assert merged[1]["status"] == "pending"

    conflicts = web_api._detect_manifest_conflicts(
        [
            {"path": "/tmp/raw-a.png", "new_path": "/tmp/a"},
            {"path": "/tmp/raw-b.png", "new_path": "/tmp/a"},
            {"new_path": ""},
            {"new_path": "/tmp/b"},
        ]
    )
    assert conflicts == [
        {
            "id": "duplicate_path:0",
            "row_id": "0",
            "type": "duplicate_path",
            "severity": "warning",
            "source_path": "/tmp/raw-a.png",
            "target_path": "/tmp/a",
            "reason": "Duplicate target path: 2 rows point to the same destination",
            "suggested_target": "",
            "status": "open",
            "row_ids": ["0", "1"],
            "count": 2,
        },
        {
            "id": "duplicate_path:1",
            "row_id": "1",
            "type": "duplicate_path",
            "severity": "warning",
            "source_path": "/tmp/raw-b.png",
            "target_path": "/tmp/a",
            "reason": "Duplicate target path: 2 rows point to the same destination",
            "suggested_target": "",
            "status": "open",
            "row_ids": ["0", "1"],
            "count": 2,
        },
    ]

    preview = web_api._build_preview_payload(
        {
            "path": "/raw/a.png",
            "new_path": "/organized/a.png",
            "status": "pending",
            "error_code": "",
            "media_type": "image",
            "sha1": "abc",
            "hash8": "abc12345",
            "ai": {"title": "Title", "notes": "Note", "tags": ["x", "y"]},
        },
        "0",
    )
    assert preview["row_id"] == "0"
    assert preview["media_type"] == "image"
    assert "Title" in str(preview["summary"])

    store = web_api.JobStore(web_api.WEB_JOB_ROOT)
    queued = store.create("analyze", {"manifest_path": str(web_api.MANIFEST_ROOT / "queued.jsonl")})
    queued_cancelled = store.request_cancel(queued.id)
    assert queued_cancelled is not None
    assert queued_cancelled.status == "cancelled"
    assert store.mark_running(queued.id) is False

    succeeded = store.create("apply", {"manifest_path": str(web_api.MANIFEST_ROOT / "ok.jsonl")})
    store.mark_running(succeeded.id)
    store.mark_succeeded(
        succeeded.id,
        {
            "dry_run": True,
            "source_manifest_path": str((web_api.MANIFEST_ROOT / "ok.jsonl").resolve()),
        },
    )
    assert store.request_cancel("missing") is None
    assert store.request_cancel(succeeded.id) is not None
    assert store.has_dry_run_success(web_api.MANIFEST_ROOT / "ok.jsonl") is True


def test_web_api_validation_errors_and_static_hosting(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    missing_dir = client.post("/api/jobs/analyze", json={"input_mode": "directory", "offline": True})
    assert missing_dir.status_code == 202

    invalid_mode = client.post(
        "/api/jobs/analyze",
        data={"input_mode": "weird", "input_directory": "~/.fileyard/workspaces/default/data/raw"},
    )
    assert invalid_mode.status_code == 400

    empty_upload = client.post("/api/jobs/analyze", data={"input_mode": "upload"})
    assert empty_upload.status_code == 400

    missing_manifest = client.post("/api/jobs/apply", json={"manifest_path": str(tmp_path / "missing.jsonl")})
    assert missing_manifest.status_code == 400

    no_manifest_job = client.post("/api/jobs/rollback", json={"analyze_job_id": "job_missing"})
    assert no_manifest_job.status_code == 404

    # Placeholder branch when dist is missing.
    placeholder = client.get("/app")
    assert placeholder.status_code == 503
    placeholder_slash = client.get("/app/")
    assert placeholder_slash.status_code == 503

    # Static hosting branch when dist exists.
    dist_dir = web_api.FRONTEND_DIST_ROOT
    asset_dir = dist_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html><body>ui</body></html>", encoding="utf-8")
    (asset_dir / "demo.js").write_text("console.log('ok')", encoding="utf-8")

    hosted_app = web_api.create_app(command_executor=_fake_executor)
    hosted_client = TestClient(hosted_app)
    assert hosted_client.get("/app").status_code == 200
    assert hosted_client.get("/app/").status_code == 200
    assert hosted_client.get("/app/assets/demo.js").status_code == 200
    assert hosted_client.get("/assets/demo.js").status_code == 200
    assert hosted_client.get("/app/anything").status_code == 200
    traversal_resp = hosted_client.get("/app/..%2F..%2Fsecret.txt")
    assert traversal_resp.status_code == 200
    assert "ui" in traversal_resp.text
    assert "secret" not in traversal_resp.text
    traversal = hosted_client.get("/app/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd")
    assert traversal.status_code in {200, 404}
    assert "root:" not in traversal.text


def test_default_command_executor_success_failure_and_cancel(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    emitted: list[tuple[str, str, dict[str, Any]]] = []

    class FakeProcess:
        def __init__(self, lines: list[str], return_code: int, wait_sequence: list[Any] | None = None):
            self.stdout = iter(lines)
            self._return_code = return_code
            self._wait_sequence = list(wait_sequence or [])
            self.terminated = False
            self.killed = False

        def wait(self, timeout: float | None = None):
            if self._wait_sequence:
                outcome = self._wait_sequence.pop(0)
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome
            return self._return_code

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    proc_ok = FakeProcess(["hello\n", "world\n"], 0)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: proc_ok)
    web_api._default_command_executor(
        ["python", "tool.py"],
        web_api.REPO_ROOT,
        lambda level, message, fields: emitted.append((level, message, fields)),
        lambda: False,
    )
    assert any(message == "command_start" for _, message, _ in emitted)
    assert any(message == "command_output" for _, message, _ in emitted)
    assert any(message == "command_success" for _, message, _ in emitted)

    emitted.clear()
    proc_fail = FakeProcess([], 9)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: proc_fail)
    try:
        web_api._default_command_executor(
            ["python", "tool.py"],
            web_api.REPO_ROOT,
            lambda level, message, fields: emitted.append((level, message, fields)),
            lambda: False,
        )
    except RuntimeError as exc:
        assert "exit code 9" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")
    assert any(message == "command_failed" for _, message, _ in emitted)

    emitted.clear()
    proc_cancel = FakeProcess(["first\n"], 0, wait_sequence=[subprocess.TimeoutExpired(cmd="x", timeout=2)])
    cancel_state = {"count": 0}

    def should_cancel() -> bool:
        cancel_state["count"] += 1
        return cancel_state["count"] >= 2

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: proc_cancel)
    try:
        web_api._default_command_executor(
            ["python", "tool.py"],
            web_api.REPO_ROOT,
            lambda level, message, fields: emitted.append((level, message, fields)),
            should_cancel,
        )
    except web_api.JobCancelled:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected JobCancelled")
    assert proc_cancel.terminated is True
    assert proc_cancel.killed is True
    assert any(message == "command_cancelled" for _, message, _ in emitted)


def test_job_store_has_dry_run_success_covers_negative_paths(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    store = web_api.JobStore(web_api.WEB_JOB_ROOT)
    target_manifest = (web_api.MANIFEST_ROOT / "target.jsonl").resolve()
    target_manifest.write_text("", encoding="utf-8")

    analyze_job = store.create("analyze", {})
    store.mark_running(analyze_job.id)
    store.mark_succeeded(analyze_job.id, {"dry_run": True, "source_manifest_path": str(target_manifest)})

    failed_apply = store.create("apply", {})
    store.mark_running(failed_apply.id)
    store.mark_failed(failed_apply.id, "boom")

    nondry_apply = store.create("apply", {})
    store.mark_running(nondry_apply.id)
    store.mark_succeeded(nondry_apply.id, {"dry_run": False, "source_manifest_path": str(target_manifest)})

    missing_source = store.create("apply", {})
    store.mark_running(missing_source.id)
    store.mark_succeeded(missing_source.id, {"dry_run": True})

    bad_source = store.create("apply", {})
    store.mark_running(bad_source.id)
    store.mark_succeeded(bad_source.id, {"dry_run": True, "source_manifest_path": "\0bad"})

    assert store.has_dry_run_success(target_manifest) is False

    good_apply = store.create("apply", {})
    store.mark_running(good_apply.id)
    store.mark_succeeded(good_apply.id, {"dry_run": True, "source_manifest_path": str(target_manifest)})
    assert store.has_dry_run_success(target_manifest) is True


def test_job_store_load_persisted_jobs_filters_invalid_entries(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    store = web_api.JobStore(web_api.WEB_JOB_ROOT)
    job_dir = store.job_dir("job_load_1")
    job_dir.mkdir(parents=True, exist_ok=True)
    store.events_file("job_load_1").write_text(
        "\n".join(
            [
                "",
                "{not-json}",
                json.dumps(
                    {
                        "seq": 3,
                        "timestamp": web_api._now_iso(),
                        "level": "info",
                        "message": "ok",
                        "fields": {"x": 1},
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    store.job_file("job_load_1").write_text(
        json.dumps(
            {
                "id": "job_load_1",
                "kind": "apply",
                "status": "mystery-status",
                "phase_label": "done",
                "progress": 1.2,
                "created_at": web_api._now_iso(),
                "summary": {"dry_run": True},
                "payload": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    invalid_dir = store.job_dir("job_load_invalid")
    invalid_dir.mkdir(parents=True, exist_ok=True)
    store.job_file("job_load_invalid").write_text(
        json.dumps({"id": "job_load_invalid", "kind": "weird", "status": "queued"}, ensure_ascii=False),
        encoding="utf-8",
    )
    store.index_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {"id": "job_load_1"},
                    {"id": "job_load_1"},
                    {"id": "job_load_missing"},
                    {"id": "job_load_invalid"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    reloaded = web_api.JobStore(web_api.WEB_JOB_ROOT)
    payload = reloaded.get("job_load_1")
    assert payload is not None
    assert payload.status == "failed"
    assert len(payload.events) == 1
    assert reloaded.get("job_load_invalid") is None
    assert reloaded.get("job_load_missing") is None


def test_web_api_missing_job_and_empty_payload_error_paths(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    assert client.get("/api/jobs/job_missing").status_code == 404
    assert client.get("/api/jobs/job_missing/events").status_code == 404
    assert client.post("/api/jobs/job_missing/cancel").status_code == 404
    assert client.post("/api/jobs/job_missing/retry").status_code == 404
    assert client.get("/api/jobs/job_missing/manifest").status_code == 404
    assert client.get("/api/jobs/job_missing/manifest/view").status_code == 404
    assert client.get("/api/jobs/job_missing/manifest/conflicts").status_code == 404
    assert client.get("/api/jobs/job_missing/report").status_code == 404
    assert client.get("/api/jobs/job_missing/audit").status_code == 404

    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "single.png").write_bytes(b"x")
    analyze_resp = client.post("/api/jobs/analyze", json={"input_mode": "directory", "input_directory": str(raw), "offline": True})
    analyze_job_id = analyze_resp.json()["id"]
    _wait_job(client, analyze_job_id)

    empty_patch = client.patch(f"/api/jobs/{analyze_job_id}/manifest/rows/0", json={"patch": {}})
    assert empty_patch.status_code == 400
    assert "patch cannot be empty" in empty_patch.json()["detail"]

    empty_batch = client.post(f"/api/jobs/{analyze_job_id}/manifest/batch", json={"operations": []})
    assert empty_batch.status_code == 400
    assert "operations cannot be empty" in empty_batch.json()["detail"]

    empty_resolve = client.post(f"/api/jobs/{analyze_job_id}/manifest/conflicts/resolve", json={"resolutions": []})
    assert empty_resolve.status_code == 400
    assert "resolutions cannot be empty" in empty_resolve.json()["detail"]

    assert client.delete("/api/preferences/views", params={"key": "missing"}).status_code == 404
    assert client.delete("/api/preferences/naming-templates", params={"key": "missing"}).status_code == 404


def test_web_api_manifest_and_report_conflict_paths(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "single.png").write_bytes(b"x")
    analyze_resp = client.post("/api/jobs/analyze", json={"input_mode": "directory", "input_directory": str(raw), "offline": True})
    analyze_job_id = analyze_resp.json()["id"]
    analyze_done = _wait_job(client, analyze_job_id)

    manifest_path = Path(analyze_done["summary"]["manifest_path"])
    report_path = Path(analyze_done["summary"]["report_path"])

    manifest_path.unlink()
    assert client.get(f"/api/jobs/{analyze_job_id}/manifest").status_code == 404

    manifest_path.write_text(
        json.dumps(
            {
                "path": str((web_api.DEFAULT_INPUT_ROOT / "single.png").resolve()),
                "new_path": str((web_api.DEFAULT_OUTPUT_ROOT / "single.png").resolve()),
                "media_type": "image",
                "run_id": "run_restore",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path.unlink()
    assert client.get(f"/api/jobs/{analyze_job_id}/report").status_code == 404


def test_job_report_rejects_report_path_outside_report_root(monkeypatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "single.png").write_bytes(b"x")
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    analyze_resp = client.post("/api/jobs/analyze", json={"input_mode": "directory", "input_directory": str(raw), "offline": True})
    analyze_job_id = analyze_resp.json()["id"]
    analyze_done = _wait_job(client, analyze_job_id)
    assert analyze_done["status"] == "succeeded"

    outside_report = tmp_path / "outside-report.json"
    outside_report.write_text("{}", encoding="utf-8")

    store = app.state.job_store
    record = store.get(analyze_job_id)
    assert record is not None
    summary = dict(record.summary)
    summary["report_path"] = str(outside_report.resolve())
    record.summary = summary
    with store._lock:
        store._jobs[analyze_job_id] = record
        store._write_job_locked(record)
        store._write_index_locked()

    report_resp = client.get(f"/api/jobs/{analyze_job_id}/report")
    assert report_resp.status_code == 400
    assert "outside controlled roots" in report_resp.json()["detail"].lower()


def test_web_api_helper_branches_for_resolve_and_executor(monkeypatch, tmp_path: Path):
    _prepare_env(monkeypatch, tmp_path)

    missing_dir = web_api.DEFAULT_INPUT_ROOT / "missing-dir"
    with pytest.raises(web_api.HTTPException) as missing_exc:
        web_api._ensure_controlled_directory(missing_dir)
    assert missing_exc.value.status_code == 400

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    with pytest.raises(web_api.HTTPException) as outside_exc:
        web_api._ensure_controlled_directory(outside_dir)
    assert outside_exc.value.status_code == 400

    store = web_api.JobStore(web_api.WEB_JOB_ROOT)
    with pytest.raises(web_api.HTTPException) as no_manifest_exc:
        web_api._resolve_manifest_path(store, None, None)
    assert no_manifest_exc.value.status_code == 400

    missing_file = web_api.MANIFEST_ROOT / "missing.jsonl"
    with pytest.raises(web_api.HTTPException) as missing_file_exc:
        web_api._resolve_manifest_path(store, None, str(missing_file))
    assert missing_file_exc.value.status_code == 404

    job = store.create("analyze", {})
    with pytest.raises(web_api.HTTPException) as no_output_exc:
        web_api._resolve_manifest_path(store, job.id, None)
    assert no_output_exc.value.status_code == 409

    def level_executor(command, cwd, emit):
        emit("warn", "warn-msg", {})
        emit("error", "err-msg", {})
        emit("info", "info-msg", {})

    runner = web_api.JobRunner(store, command_executor=level_executor)
    sink = web_api.EventSink(store, job.id)
    runner.run_command(["python", "noop"], web_api.REPO_ROOT, sink)
    record = store.get(job.id)
    assert record is not None
    messages = [event.message for event in record.events]
    assert "warn-msg" in messages
    assert "err-msg" in messages
    assert "info-msg" in messages
