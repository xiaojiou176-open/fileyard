import argparse
import json
from pathlib import Path

from packages.application.apply_changes import cmd_apply, cmd_rollback

from packages.application import apply_changes
from packages.domain.core_utils import sha1_file
from packages.infrastructure.manifest_store import read_jsonl_list, write_jsonl


def test_apply_and_rollback(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"data")

    sha1 = sha1_file(src)
    row = {
        "path": str(src),
        "input_root": str(input_root),
        "sha1": sha1,
        "hash8": sha1[:8],
        "file_mtime": "2025-01-01T12:00:00",
        "media_type": "image",
        "ai": {
            "kind": "截图",
            "category": "工作",
            "title": "测试",
            "tags": [],
            "confidence": 0.9,
            "notes": "",
        },
        "error": "",
    }

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=False,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=True,
        fsync_interval=0,
    )

    cmd_apply(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0].get("new_path")
    moved_path = Path(rows[0]["new_path"])
    assert moved_path.exists()
    assert not src.exists()

    rollback_args = argparse.Namespace(
        manifest=str(manifest),
        dry_run=False,
        overwrite=False,
        allowed_root=str(tmp_path),
    )
    cmd_rollback(rollback_args)

    assert src.exists()
    assert not moved_path.exists()


def test_rollback_logs_skip_summary(tmp_path: Path, monkeypatch):
    src_missing = tmp_path / "missing.txt"
    src_existing = tmp_path / "existing.txt"
    src_existing.write_text("payload", encoding="utf-8")
    dst_existing = tmp_path / "dst-existing.txt"
    dst_existing.write_text("occupied", encoding="utf-8")

    manifest = tmp_path / "rollback_manifest.jsonl"
    rows = [
        {"path": str(tmp_path / "invalid.txt"), "media_type": "image"},
        {
            "path": str(tmp_path / "target-a.txt"),
            "new_path": str(src_missing),
            "media_type": "image",
        },
        {"path": str(dst_existing), "new_path": str(src_existing), "media_type": "image"},
    ]
    manifest.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    events = []
    original_log_event = apply_changes.log_event

    def _capture(logger, level, event, message, **fields):
        events.append((event, fields))
        return original_log_event(logger, level, event, message, **fields)

    monkeypatch.setattr(apply_changes, "log_event", _capture)
    rollback_args = argparse.Namespace(manifest=str(manifest), dry_run=False, overwrite=False, allowed_root=str(tmp_path))
    cmd_rollback(rollback_args)

    summary = [fields for event, fields in events if event == "rollback_skipped"]
    assert summary
    fields = summary[-1]
    assert fields.get("skipped_invalid") == 1
    assert fields.get("skipped_missing_src") == 1
    assert fields.get("skipped_existing_dst") == 1


def test_rollback_allowed_root_skips_outside_row_without_blocking_valid_row(tmp_path: Path, monkeypatch):
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()

    outside_src = tmp_path / "outside_src.txt"
    outside_src.write_text("outside", encoding="utf-8")
    outside_dst = tmp_path / "outside_dst.txt"

    inside_src = allowed_root / "inside_src.txt"
    inside_src.write_text("inside", encoding="utf-8")
    inside_dst = allowed_root / "inside_dst.txt"

    manifest = tmp_path / "rollback_manifest_allowed_root.jsonl"
    rows = [
        {"path": str(outside_dst), "new_path": str(outside_src), "media_type": "image"},
        {"path": str(inside_dst), "new_path": str(inside_src), "media_type": "image"},
    ]
    manifest.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    events = []
    original_log_event = apply_changes.log_event

    def _capture(logger, level, event, message, **fields):
        events.append((event, fields))
        return original_log_event(logger, level, event, message, **fields)

    monkeypatch.setattr(apply_changes, "log_event", _capture)
    rollback_args = argparse.Namespace(
        manifest=str(manifest),
        dry_run=False,
        overwrite=False,
        allowed_root=str(allowed_root),
    )
    cmd_rollback(rollback_args)

    assert outside_src.exists()
    assert not outside_dst.exists()
    assert not inside_src.exists()
    assert inside_dst.read_text(encoding="utf-8") == "inside"

    outside_events = [fields for event, fields in events if event == "rollback_skip_outside_allowed_root"]
    assert outside_events
    summary = [fields for event, fields in events if event == "rollback_skipped"]
    assert summary
    assert summary[-1].get("skipped_invalid") == 1


def test_rollback_allowed_root_keeps_valid_row_restorable(tmp_path: Path, monkeypatch):
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()

    src = allowed_root / "inside_src.txt"
    src.write_text("payload", encoding="utf-8")
    dst = allowed_root / "inside_dst.txt"

    manifest = tmp_path / "rollback_manifest_allowed_root_valid.jsonl"
    row = {"path": str(dst), "new_path": str(src), "media_type": "image"}
    manifest.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    events = []
    original_log_event = apply_changes.log_event

    def _capture(logger, level, event, message, **fields):
        events.append((event, fields))
        return original_log_event(logger, level, event, message, **fields)

    monkeypatch.setattr(apply_changes, "log_event", _capture)
    rollback_args = argparse.Namespace(
        manifest=str(manifest),
        dry_run=False,
        overwrite=False,
        allowed_root=str(allowed_root),
    )
    cmd_rollback(rollback_args)

    assert not src.exists()
    assert dst.read_text(encoding="utf-8") == "payload"

    outside_events = [fields for event, fields in events if event == "rollback_skip_outside_allowed_root"]
    assert not outside_events
    restored = [fields for event, fields in events if event == "restored_files"]
    assert restored
    assert restored[-1].get("count") == 1
