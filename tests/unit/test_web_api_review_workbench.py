from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from fastapi.testclient import TestClient

from apps.api import web_api


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

    if should_cancel and should_cancel():
        raise web_api.JobCancelled("cancel requested after fake executor")

    emit("info", "fake_command_done", {"subcommand": subcommand})


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
    cli_entrypoint = repo / "apps" / "cli" / "movi_organizer.py"
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


def test_review_queue_endpoint_returns_triage_summary(monkeypatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample.png").write_bytes(b"fake")
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    resp = client.post("/api/jobs/analyze", json={"input_mode": "directory", "input_directory": str(raw), "offline": True})
    assert resp.status_code == 202
    job_id = resp.json()["id"]
    _wait_job(client, job_id)

    queue = client.get(f"/api/jobs/{job_id}/review-queue")
    assert queue.status_code == 200
    payload = queue.json()
    assert payload["summary"]["total"] == 1
    assert payload["rows"][0]["review_bucket"] in {"auto_safe", "needs_review", "conflict", "blocked"}
    assert payload["copilot_summary"]["mode"] == "deterministic-review-summary"
    assert payload["copilot_summary"]["guardrails"]["execute_allowed"] is False
    assert payload["rows"][0]["review_explainability"]["bucket"] == payload["rows"][0]["review_bucket"]
    assert payload["rows"][0]["review_explainability"]["reason_codes"]


def test_review_queue_batch_triage_and_rule_draft_from_examples(monkeypatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    raw = web_api.DEFAULT_INPUT_ROOT
    (raw / "sample-a.png").write_bytes(b"fake")
    (raw / "sample-b.png").write_bytes(b"fake")
    app = web_api.create_app(command_executor=_fake_executor)
    client = TestClient(app)

    resp = client.post("/api/jobs/analyze", json={"input_mode": "directory", "input_directory": str(raw), "offline": True})
    assert resp.status_code == 202
    job_id = resp.json()["id"]
    _wait_job(client, job_id)

    queue = client.get(f"/api/jobs/{job_id}/review-queue")
    assert queue.status_code == 200
    row_ids = [row["row_id"] for row in queue.json()["rows"][:2]]

    draft_resp = client.post(
        f"/api/jobs/{job_id}/review-rules/from-examples",
        json={"row_ids": row_ids, "name": "Draft from receipts"},
    )
    assert draft_resp.status_code == 200
    draft_payload = draft_resp.json()
    assert draft_payload["draft"]["name"] == "Draft from receipts"
    assert draft_payload["draft"]["actions"]["set_category"] == "工作"
    assert draft_payload["mode"] == "draft_only"
    assert draft_payload["save_allowed"] is False
    assert draft_payload["apply_allowed"] is False
    assert draft_payload["execute_allowed"] is False
    assert draft_payload["draft"]["explainability"]["save_allowed"] is False

    triage_resp = client.post(
        f"/api/jobs/{job_id}/review-queue/batch-triage",
        json={"row_ids": [row_ids[0]], "set_ignore": True},
    )
    assert triage_resp.status_code == 200
    triage_payload = triage_resp.json()
    assert triage_payload["applied_count"] == 1
    assert triage_payload["mode"] == "overlay_only"
    assert triage_payload["execute_allowed"] is False
    assert any(row.get("ignore") is True for row in triage_payload["rows"])

    apply_resp = client.post(
        f"/api/jobs/{job_id}/review-rules/apply",
        json={
            "rule": {
                "name": "Ignore receipts",
                "scope": "manifest",
                "conditions": {"media_types": ["image"]},
                "actions": {"set_ignore": True},
            }
        },
    )
    assert apply_resp.status_code == 200
    apply_payload = apply_resp.json()
    assert apply_payload["mode"] == "overlay_only"
    assert apply_payload["execute_allowed"] is False
    assert apply_payload["matched_count"] >= 1


def test_review_rules_and_strategy_packs_and_watch_sources_routes(monkeypatch, tmp_path: Path) -> None:
    _prepare_env(monkeypatch, tmp_path)
    strategy_dir = web_api.REPO_ROOT / "contracts" / "strategies"
    strategy_dir.mkdir(parents=True, exist_ok=True)
    for name in ("travel", "receipts", "chat-export", "meeting-notes"):
        (strategy_dir / f"{name}.yaml").write_text(
            "\n".join(
                [
                    f"id: {name}",
                    f"name: {name.title()}",
                    "description: fixture strategy pack",
                    "categories:",
                    "  - 工作",
                    "workers: 1",
                    "review_confidence_threshold: 0.8",
                    "default_rule_ids: []",
                    "default_template_patterns: []",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
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

    rule_resp = client.post(
        "/api/preferences/review-rules",
        json={
            "name": "Travel images",
            "scope": "manifest",
            "conditions": {"media_types": ["image"]},
            "actions": {"set_category": "旅行"},
        },
    )
    assert rule_resp.status_code == 200
    listed_rules = client.get("/api/preferences/review-rules")
    assert listed_rules.status_code == 200
    assert listed_rules.json()["count"] >= 1

    packs = client.get("/api/preferences/strategy-packs")
    assert packs.status_code == 200
    assert packs.json()["count"] >= 4
    assert packs.json()["active_pack"] is None

    source_root = Path(tmp_path) / "watch-source"
    source_root.mkdir()
    (source_root / "note.txt").write_text("hello", encoding="utf-8")
    watch_resp = client.post(
        "/api/preferences/watch-sources",
        json={"name": "Inbox", "input_root": str(source_root), "enabled": True, "strategy_pack_id": "travel"},
    )
    assert watch_resp.status_code == 200
    listed_watch = client.get("/api/preferences/watch-sources")
    assert listed_watch.status_code == 200
    assert listed_watch.json()["items"][0]["strategy_pack"]["id"] == "travel"
    inbox_resp = client.post("/api/inbox/scan")
    assert inbox_resp.status_code == 200
    assert inbox_resp.json()["count"] == 1
    assert inbox_resp.json()["mode"] == "discovery_only"
    assert inbox_resp.json()["items"][0]["analyze_job_id"] == ""
    assert inbox_resp.json()["items"][0]["strategy_pack"]["id"] == "travel"
    assert inbox_resp.json()["items"][0]["analyze_defaults"]["categories"] == "工作"
    assert not captured_commands

    analyze_resp = client.post(
        "/api/inbox/analyze",
        json={"watch_source_id": watch_resp.json()["id"], "batch_id": inbox_resp.json()["items"][0]["id"], "offline": True},
    )
    assert analyze_resp.status_code == 200 or analyze_resp.status_code == 202
    analyze_payload = analyze_resp.json()
    assert analyze_payload["mode"] == "explicit_inbox_action"
    assert analyze_payload["batch"]["analyze_job_id"]
    assert analyze_payload["review_next"]["execute_allowed"] is False
    _wait_job(client, analyze_payload["job_id"])
    analyze_command = next(command for command in captured_commands if command[2] == "analyze")
    assert analyze_command[analyze_command.index("--workers") + 1] == "1"
    assert analyze_command[analyze_command.index("--categories") + 1] == "工作"
    assert inbox_resp.json()["items"][0]["analyze_ready"] is True
    assert inbox_resp.json()["items"][0]["strategy_pack"]["id"] == "travel"

    analyze_resp = client.post(
        "/api/inbox/analyze",
        json={"watch_source_id": watch_resp.json()["id"]},
    )
    assert analyze_resp.status_code == 202
    assert analyze_resp.json()["job_id"]
    _wait_job(client, analyze_resp.json()["job_id"])
    assert analyze_resp.json()["review_next"]["review_queue_path"].startswith("/api/jobs/")
