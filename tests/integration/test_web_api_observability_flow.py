from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Sequence

import pytest
from fastapi.testclient import TestClient

from apps.api import web_api


def _extract_arg(command: Sequence[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _prepare_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    artifacts = workspace / ".fileman" / "artifacts"
    manifests = workspace / ".fileman" / "manifests"
    input_root = workspace / "data" / "raw"
    output_root = workspace / "data" / "organized"
    cli_entrypoint = repo / "apps" / "cli" / "fileman.py"
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
    (workspace / ".fileman" / "preferences").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(web_api, "REPO_ROOT", repo)
    monkeypatch.setattr(web_api, "CLI_ENTRYPOINT", cli_entrypoint)
    monkeypatch.setattr(web_api, "WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(web_api, "WEB_ARTIFACT_ROOT", artifacts / "web_api")
    monkeypatch.setattr(web_api, "WEB_JOB_ROOT", artifacts / "web_api" / "jobs")
    monkeypatch.setattr(web_api, "WEB_UPLOAD_ROOT", artifacts / "web_api" / "uploads")
    monkeypatch.setattr(web_api, "PREFERENCE_ROOT", workspace / ".fileman" / "preferences")
    monkeypatch.setattr(web_api, "MANIFEST_ROOT", manifests)
    monkeypatch.setattr(web_api, "REPORT_ROOT", artifacts / "report")
    monkeypatch.setattr(web_api, "ROLLBACK_ROOT", artifacts / "rollback")
    monkeypatch.setattr(web_api, "DEFAULT_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(web_api, "DEFAULT_INPUT_ROOT", input_root)
    monkeypatch.setattr(web_api, "DEFAULT_ALLOWED_ROOT", f"{input_root},{output_root}")
    monkeypatch.setattr(web_api, "FRONTEND_DIST_ROOT", frontend_dist)


def _fake_analyze_executor(
    command: Sequence[str],
    cwd: Path,
    emit: Callable[[str, str, dict[str, Any]], None],
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    if should_cancel and should_cancel():
        raise web_api.JobCancelled("cancel requested before fake executor")

    emit("info", "fake_command_start", {"command": " ".join(command), "cwd": str(cwd)})
    subcommand = command[2]
    if subcommand != "analyze":
        raise RuntimeError(f"unexpected command: {command}")

    manifest = Path(_extract_arg(command, "--manifest"))
    report = Path(_extract_arg(command, "--report"))
    csv = Path(_extract_arg(command, "--csv"))
    input_root = Path(_extract_arg(command, "--input"))

    manifest.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    csv.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(path for path in input_root.iterdir() if path.is_file())
    if not files:
        files = [input_root / "sample.png"]

    rows: list[dict[str, Any]] = []
    for idx, file_path in enumerate(files, start=1):
        rows.append(
            {
                "path": str(file_path.resolve()),
                "input_root": str(input_root.resolve()),
                "media_type": "image",
                "sha1": ("b" * 38) + f"{idx:02d}",
                "hash8": f"bbbbbb{idx:02d}"[:8],
                "file_mtime": "2026-01-01T00:00:00",
                "run_id": f"run_web_api_obs_{idx}",
                "ai": {
                    "kind": "screenshot",
                    "category": "work",
                    "title": f"obs-sample-{idx}",
                    "tags": ["integration"],
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
                "by_kind": {"screenshot": len(rows)},
                "by_category": {"work": len(rows)},
                "by_status": {"pending": len(rows)},
                "error_codes": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    csv.write_text("path,ai_kind\n" + "\n".join([f"{Path(row['path']).name},screenshot" for row in rows]) + "\n", encoding="utf-8")

    if should_cancel and should_cancel():
        raise web_api.JobCancelled("cancel requested after fake executor")
    emit("info", "fake_command_done", {"subcommand": subcommand})


def _wait_job(client: TestClient, job_id: str, timeout_s: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in web_api.TERMINAL_JOB_STATUSES:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"job timeout: {job_id}")


def test_web_api_analyze_history_events_audit_consistency(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "observability_sample.png").write_bytes(b"fake-image")

    app = web_api.create_app(command_executor=_fake_analyze_executor)
    with TestClient(app) as client:
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

        job_payload = _wait_job(client, job_id)
        assert job_payload["status"] == "succeeded"

        history_resp = client.get("/api/jobs/history", params={"limit": 10})
        assert history_resp.status_code == 200
        history_payload = history_resp.json()
        history_item = next(item for item in history_payload["items"] if item["id"] == job_id)

        events_resp = client.get(f"/api/jobs/{job_id}/events")
        assert events_resp.status_code == 200
        events_payload = events_resp.json()
        events = events_payload["events"]
        assert events_payload["job_id"] == job_id
        assert len(events) >= 6
        assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
        messages = [event["message"] for event in events]
        assert messages[0] == "job_created"
        assert messages[-1] == "job_succeeded"
        assert "fake_command_start" in messages
        assert "fake_command_done" in messages

        audit_resp = client.get(f"/api/jobs/{job_id}/audit", params={"tail": 5000})
        assert audit_resp.status_code == 200
        audit_payload = audit_resp.json()

    assert history_item["status"] == job_payload["status"]
    assert history_item["summary"] == job_payload["summary"]

    assert audit_payload["job"]["id"] == job_id
    assert audit_payload["job"]["status"] == history_item["status"]
    assert audit_payload["summary"] == history_item["summary"]
    assert audit_payload["event_count"] == len(events)
    assert audit_payload["events_tail"] == events

    manifest_path = Path(job_payload["summary"]["manifest_path"])
    events_jsonl_path = Path(audit_payload["paths"]["events_jsonl_path"])
    index_path = Path(history_payload["index_path"])

    assert manifest_path.exists()
    assert events_jsonl_path.exists()
    assert index_path.exists()
    assert str(manifest_path) == history_item["summary"]["manifest_path"]
    assert str(events_jsonl_path) == audit_payload["paths"]["events_jsonl_path"]

    persisted_events = _read_jsonl(events_jsonl_path)
    assert persisted_events == events


def test_web_api_rollback_strict_integrity_missing_key_rejected_before_queue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    monkeypatch.delenv("FILEMAN_ROLLBACK_HMAC_KEY", raising=False)

    good_manifest = web_api.MANIFEST_ROOT / "rollback-strict-missing-key.jsonl"
    good_manifest.write_text(
        json.dumps(
            {
                "path": str((web_api.DEFAULT_INPUT_ROOT / "x.png").resolve()),
                "new_path": str((web_api.DEFAULT_OUTPUT_ROOT / "x.png").resolve()),
                "media_type": "image",
                "run_id": "run_web_api_obs_rollback_missing_key",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    app = web_api.create_app(command_executor=_fake_analyze_executor)
    with TestClient(app) as client:
        jobs_before = len(client.get("/api/jobs").json())
        resp = client.post(
            "/api/jobs/rollback",
            json={
                "manifest_path": str(good_manifest),
                "execute": False,
                "strict_integrity": True,
            },
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "strict_integrity=true requires FILEMAN_ROLLBACK_HMAC_KEY"
        assert len(client.get("/api/jobs").json()) == jobs_before


def test_web_api_review_routes_keep_draft_and_batch_actions_inside_review_layer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "review-a.png").write_bytes(b"fake-a")
    (raw / "review-b.png").write_bytes(b"fake-b")

    app = web_api.create_app(command_executor=_fake_analyze_executor)
    with TestClient(app) as client:
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
        _wait_job(client, job_id)

        queue_resp = client.get(f"/api/jobs/{job_id}/review-queue")
        assert queue_resp.status_code == 200
        queue_payload = queue_resp.json()
        row_ids = [row["row_id"] for row in queue_payload["rows"][:2]]
        assert queue_payload["rows"][0]["review_explainability"]["reason_codes"]

        draft_resp = client.post(
            f"/api/jobs/{job_id}/review-rules/from-examples",
            json={"row_ids": row_ids, "name": "Integration draft"},
        )
        assert draft_resp.status_code == 200
        draft_payload = draft_resp.json()
        assert draft_payload["mode"] == "draft_only"
        assert draft_payload["save_allowed"] is False
        assert draft_payload["apply_allowed"] is False

        triage_resp = client.post(
            f"/api/jobs/{job_id}/review-queue/batch-triage",
            json={"row_ids": [row_ids[0]], "set_ignore": True},
        )
        assert triage_resp.status_code == 200
        triage_payload = triage_resp.json()
        assert triage_payload["mode"] == "overlay_only"
        assert triage_payload["execute_allowed"] is False
