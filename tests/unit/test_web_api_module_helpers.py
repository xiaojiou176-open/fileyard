from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from apps.api.web_api_core import (
    _now_iso,
    _parse_form_bool,
    _read_json_file,
    _read_manifest_rows,
    _safe_float_progress,
    _safe_relative_descendant,
    _sanitize_filename,
    _within_root,
    _write_json_atomic,
    _write_jsonl_rows,
)
from apps.api.web_api_models import (
    AnalyzeJsonRequest,
    ApplyRequest,
    InboxAnalyzeRequest,
    JobEvent,
    JobRecord,
    JobView,
    ManifestBatchOperation,
    ManifestBatchRequest,
    ManifestConflictResolution,
    ManifestConflictResolveRequest,
    ManifestRowPatchRequest,
    PreferenceUpsertRequest,
    RollbackRequest,
)
from apps.api.web_api_routes import (
    MANIFEST_EDITABLE_EXTRA_FIELDS,
    apply_overlay_rows,
    build_preview_payload,
    coerce_row_index,
    detect_manifest_conflicts,
    ensure_controlled_directory,
    get_manifest_path_for_job,
    load_overlay,
    overlay_default,
    read_preference_items,
    resolve_manifest_path,
    save_overlay,
    sse,
    validate_manifest_for_rollback,
    write_preference_items,
)
from apps.api.web_api_store import JobStore


def test_web_api_models_validate_and_forbid_extra_fields() -> None:
    assert AnalyzeJsonRequest(input_mode="directory", offline=True).input_mode == "directory"
    assert AnalyzeJsonRequest(input_mode="directory", strategy_pack_id="travel", trigger_source="inbox").strategy_pack_id == "travel"
    assert InboxAnalyzeRequest(watch_source_id="source-1", batch_id="batch-1").watch_source_id == "source-1"
    assert ApplyRequest(execute=True).execute is True
    assert RollbackRequest(strict_integrity=False).strict_integrity is False
    assert ManifestRowPatchRequest(patch={"ai": {"title": "x"}}).patch["ai"]["title"] == "x"
    assert ManifestBatchRequest(operations=[ManifestBatchOperation(row_id="0", patch={"ignore": True})]).operations[0].row_id == "0"
    assert ManifestConflictResolveRequest(resolutions=[ManifestConflictResolution(row_id="1", new_path="x")]).resolutions[0].new_path == "x"
    assert PreferenceUpsertRequest(key="jobs", value={"q": "error"}).key == "jobs"

    record = JobRecord(
        id="job_1",
        kind="analyze",
        status="queued",
        phase_label="queued",
        progress=0.0,
        created_at="2026-01-01T00:00:00Z",
    )
    assert JobEvent(seq=1, timestamp="2026-01-01T00:00:00Z", level="info", message="created").message == "created"
    assert JobView(id=record.id, kind=record.kind, status=record.status, phase_label="queued", phase="queued", progress=0.0).id == "job_1"

    with pytest.raises(ValidationError):
        AnalyzeJsonRequest(input_mode="directory", extra_field=True)  # type: ignore[call-arg]


def test_web_api_core_helpers_cover_io_and_parsing(tmp_path: Path) -> None:
    now_iso = _now_iso()
    assert now_iso.endswith("Z")
    assert _within_root(tmp_path / "a" / "b", tmp_path) is True
    assert _within_root(Path("/tmp"), tmp_path) is False
    assert _within_root(tmp_path / ".." / "escape.txt", tmp_path) is False
    assert _sanitize_filename("", 7) == "upload-0007.bin"
    assert _sanitize_filename("../report.txt", 1) == "report.txt"
    assert _safe_float_progress(-1) == 0.0
    assert _safe_float_progress(9) == 1.0
    assert _safe_float_progress(0.123456) == 0.1235

    target = tmp_path / "payload.json"
    _write_json_atomic(target, {"ok": True}, root=tmp_path)
    assert _read_json_file(target, {"ok": False}) == {"ok": True}
    assert _read_json_file(tmp_path / "missing.json", {"fallback": True}) == {"fallback": True}

    manifest = tmp_path / "manifest.jsonl"
    _write_jsonl_rows(
        manifest,
        [
            {"path": str(tmp_path / "a.png"), "media_type": "image"},
            {"path": str(tmp_path / "b.wav"), "media_type": "audio"},
        ],
    )
    rows = _read_manifest_rows(manifest)
    assert [row["media_type"] for row in rows] == ["image", "audio"]

    assert _parse_form_bool(None, default=True) is True
    assert _parse_form_bool("true") is True
    assert _parse_form_bool("0") is False
    assert _parse_form_bool("unknown", default=True) is True
    assert _safe_relative_descendant("../a/../../b/c.txt") == Path("a", "b", "c.txt")

    with pytest.raises(ValueError):
        _write_json_atomic(tmp_path.parent / "outside.json", {"nope": True}, root=tmp_path)

    with pytest.raises(ValueError):
        _write_json_atomic(tmp_path / ".." / "escape.json", {"nope": True}, root=tmp_path)


def test_web_api_routes_pure_helpers_and_error_branches(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    upload_root = repo_root / "artifacts" / "web_api" / "uploads"
    data_root = repo_root / "data"
    raw_root = data_root / "raw"
    raw_root.mkdir(parents=True)
    upload_root.mkdir(parents=True)

    assert MANIFEST_EDITABLE_EXTRA_FIELDS == {"ai", "new_path", "ignore"}

    ensure_controlled_directory(raw_root, repo_root, upload_root, _within_root)
    with pytest.raises(HTTPException) as outside_dir:
        ensure_controlled_directory(tmp_path / "outside", repo_root, upload_root, _within_root)
    assert outside_dir.value.status_code == 400

    with pytest.raises(HTTPException) as missing_dir:
        ensure_controlled_directory(raw_root / "missing", repo_root, upload_root, _within_root)
    assert missing_dir.value.status_code == 400

    def _raise_manifest(_: Path) -> list[dict[str, object]]:
        raise ValueError("boom")

    with pytest.raises(HTTPException) as invalid_manifest:
        validate_manifest_for_rollback(tmp_path / "bad.jsonl", _raise_manifest)
    assert invalid_manifest.value.status_code == 409

    with pytest.raises(HTTPException) as empty_manifest:
        validate_manifest_for_rollback(tmp_path / "empty.jsonl", lambda _: [])
    assert empty_manifest.value.status_code == 409

    with pytest.raises(HTTPException) as no_ready_rows:
        validate_manifest_for_rollback(tmp_path / "not-ready.jsonl", lambda _: [{"path": "a", "media_type": "image"}])
    assert no_ready_rows.value.status_code == 409

    validate_manifest_for_rollback(
        tmp_path / "ok.jsonl",
        lambda _: [{"path": "a", "new_path": "b", "run_id": "run_ok", "media_type": "image"}],
    )

    overlay_path = tmp_path / "overlay.json"
    payload = overlay_default(_now_iso, "job_x")
    assert payload["job_id"] == "job_x"
    loaded = load_overlay(_read_json_file, _now_iso, overlay_path, "job_x")
    assert loaded["rows"] == {}
    saved = save_overlay(_write_json_atomic, _now_iso, overlay_path, "job_x", {"0": {"ignore": True}})
    assert saved["rows"]["0"]["ignore"] is True
    overlay_path.write_text(json.dumps({"rows": []}, ensure_ascii=False), encoding="utf-8")
    normalized = load_overlay(_read_json_file, _now_iso, overlay_path, "job_x")
    assert normalized["rows"] == {}

    assert coerce_row_index("1", 3) == 1
    with pytest.raises(HTTPException):
        coerce_row_index("x", 1)
    with pytest.raises(HTTPException):
        coerce_row_index("9", 1)

    base_rows = [{"path": "a", "new_path": "x"}, {"path": "b", "new_path": "x"}]
    resolved = apply_overlay_rows(base_rows, {"1": {"new_path": "y"}})
    assert resolved[1]["new_path"] == "y"
    conflicts = detect_manifest_conflicts(base_rows)
    assert len(conflicts) == 2
    assert conflicts[0]["type"] == "duplicate_path"

    preview = build_preview_payload(
        {
            "path": "/tmp/raw/a.png",
            "new_path": "/tmp/out/a.png",
            "status": "pending",
            "error_code": "",
            "media_type": "image",
            "sha1": "abc",
            "hash8": "12345678",
            "mime": "image/png",
            "ai": {"title": "Title", "notes": "Notes", "tags": ["one", "two"]},
        },
        "0",
    )
    assert preview["row_id"] == "0"
    assert preview["summary"] == "Title | Notes | one, two"

    record = JobRecord(
        id="job_manifest",
        kind="analyze",
        status="succeeded",
        phase_label="done",
        progress=1.0,
        created_at="2026-01-01T00:00:00Z",
        payload={"manifest_path": str(tmp_path / "manifest.jsonl")},
    )
    (tmp_path / "manifest.jsonl").write_text('{"path":"a","media_type":"image"}\n', encoding="utf-8")
    assert get_manifest_path_for_job(record).name == "manifest.jsonl"

    assert "event: snapshot" in sse("snapshot", {"ok": True})

    pref_path = tmp_path / "prefs.json"
    assert read_preference_items(_read_json_file, pref_path) == {}
    write_preference_items(_write_json_atomic, _now_iso, pref_path, {"saved": {"value": {"q": "x"}}})
    normalized_items = read_preference_items(_read_json_file, pref_path)
    assert "saved" in normalized_items


def test_web_api_routes_manifest_resolution_paths(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")

    manifest_path = tmp_path / "manifest.jsonl"
    manifest_path.write_text('{"path":"a","media_type":"image"}\n', encoding="utf-8")
    assert resolve_manifest_path(store, None, str(manifest_path)) == manifest_path.resolve()

    with pytest.raises(HTTPException) as missing_manifest:
        resolve_manifest_path(store, None, str(tmp_path / "missing.jsonl"))
    assert missing_manifest.value.status_code == 404

    with pytest.raises(HTTPException) as missing_params:
        resolve_manifest_path(store, None, None)
    assert missing_params.value.status_code == 400

    with pytest.raises(HTTPException) as missing_job:
        resolve_manifest_path(store, "job_missing", None)
    assert missing_job.value.status_code == 404

    source = store.create("analyze", {})
    source.summary = {}
    with pytest.raises(HTTPException) as missing_summary_manifest:
        resolve_manifest_path(store, source.id, None)
    assert missing_summary_manifest.value.status_code == 409

    source.summary = {"manifest_path": str(tmp_path / "gone.jsonl")}
    with pytest.raises(HTTPException) as missing_disk_manifest:
        resolve_manifest_path(store, source.id, None)
    assert missing_disk_manifest.value.status_code == 404


def test_web_api_routes_manifest_resolution_rejects_paths_outside_allowed_roots(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    manifest_path = tmp_path / "outside.jsonl"
    manifest_path.write_text('{"path":"a","media_type":"image"}\n', encoding="utf-8")
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()

    with pytest.raises(HTTPException) as outside_manifest:
        resolve_manifest_path(
            store,
            None,
            str(manifest_path),
            allowed_roots=[allowed_root],
            within_root=_within_root,
        )
    assert outside_manifest.value.status_code == 400
