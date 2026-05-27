import argparse
from pathlib import Path

import pytest

from packages.application import apply_changes
from packages.infrastructure.manifest_store import write_jsonl


def test_cmd_apply_read_jsonl_error(monkeypatch, tmp_path):
    def fake_read_jsonl(path, validate=True):
        raise ValueError("bad")

    monkeypatch.setattr(apply_changes, "read_jsonl", fake_read_jsonl)

    args = argparse.Namespace(
        manifest=str(tmp_path / "m.jsonl"),
        output=str(tmp_path / "out"),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root="",
        verify_sha1=False,
        fsync_interval=-1,
    )

    with pytest.raises(SystemExit, match="Failed to read manifest"):
        apply_changes.cmd_apply(args)


def test_cmd_apply_partial_cleanup(monkeypatch, tmp_path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")

    sha1 = apply_changes.sha1_file(src)
    row = {
        "schema_version": 2,
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
            "confidence": 1,
            "notes": "",
        },
        "error": "",
    }

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

    def _boom(*_args, **_kwargs):
        raise RuntimeError("write")

    monkeypatch.setattr(apply_changes, "write_jsonl_line", _boom)

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=False,
        fsync_interval=0,
        durability="none",
        resume=True,
        retry_errors=False,
        log_level="INFO",
        log_json=False,
        run_id="",
        generator_version="",
        report="",
    )

    with pytest.raises(SystemExit, match="Failed to write updated manifest: write"):
        apply_changes.cmd_apply(args)

    assert not Path(str(manifest) + ".partial").exists()
    crash_files = list(tmp_path.glob("manifest.jsonl.partial.crash-*"))
    assert crash_files


def test_cmd_apply_rollback_commit_guard_keeps_manifest_trackable_when_rollback_commit_fails(monkeypatch, tmp_path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")

    sha1 = apply_changes.sha1_file(src)
    row = {
        "schema_version": 2,
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
            "confidence": 1,
            "notes": "",
        },
        "error": "",
    }
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

    original_replace = apply_changes.Path.replace

    def _replace_with_failure(self, target):
        if str(self).endswith(".rollback.jsonl.partial") and str(target).endswith(".rollback.jsonl"):
            raise RuntimeError("rollback replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(apply_changes.Path, "replace", _replace_with_failure)

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=False,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=False,
        fsync_interval=0,
        durability="none",
        resume=True,
        retry_errors=False,
        log_level="INFO",
        log_json=False,
        run_id="",
        generator_version="",
        report="",
        rollback_manifest="",
    )

    with pytest.raises(SystemExit, match="Failed to update rollback manifest: rollback replace failed"):
        apply_changes.cmd_apply(args)

    rows = list(apply_changes.read_jsonl(manifest, validate=True))
    assert len(rows) == 1
    assert rows[0].get("new_path", "")
    assert rows[0].get("status", "") == "applied"
    assert (tmp_path / "manifest.jsonl.apply.wal.json").exists()
    assert list(tmp_path.glob("manifest.jsonl.rollback.jsonl.partial.crash-*"))
