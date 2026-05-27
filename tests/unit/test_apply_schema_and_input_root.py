import argparse
import json
from pathlib import Path

import pytest

from packages.application import apply_changes
from packages.infrastructure.manifest_store import write_jsonl


def _row(path: Path, input_root: Path, sha1: str, schema_version: int):
    return {
        "schema_version": schema_version,
        "path": str(path),
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


def test_apply_schema_older_fails_fast(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    a = input_root / "a.png"
    b = input_root / "b.png"
    a.write_bytes(b"x")
    b.write_bytes(b"y")

    sha1_a = apply_changes.sha1_file(a)
    sha1_b = apply_changes.sha1_file(b)

    row_a = _row(a, input_root, sha1_a, 99)
    row_b = _row(b, input_root, sha1_b, 1)

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row_a, row_b])

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=False,
        fsync_interval=-1,
        durability="batch",
        resume=True,
        retry_errors=False,
        log_level="INFO",
        log_json=False,
        run_id="",
        generator_version="",
    )

    with pytest.raises(SystemExit, match="Manifest schema_version is older than the current version; compatibility mode is not supported"):
        apply_changes.cmd_apply(args)


def test_apply_input_root_parse_error(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "bad_root"
    output_root = tmp_path / "output"
    output_root.mkdir()

    src = tmp_path / "a.png"
    src.write_bytes(b"x")

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_row(src, tmp_path, apply_changes.sha1_file(src), 2)])

    original_resolve = apply_changes.Path.resolve

    def fake_resolve(self):
        if str(self).endswith("bad_root"):
            raise RuntimeError("bad")
        return original_resolve(self)

    monkeypatch.setattr(apply_changes.Path, "resolve", fake_resolve)

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
    )

    with pytest.raises(SystemExit, match="Failed to resolve input root: bad"):
        apply_changes.cmd_apply(args)


def test_apply_resume_missing_new_path(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")
    sha1 = apply_changes.sha1_file(src)

    row = _row(src, input_root, sha1, 2)
    row["new_path"] = str(output_root / "missing.png")
    row["status"] = "applied"

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

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
    )

    apply_changes.cmd_apply(args)
    assert src.exists()
    assert not Path(row["new_path"]).exists()


def test_apply_missing_path_row(tmp_path: Path):
    output_root = tmp_path / "output"
    output_root.mkdir()

    row = _row(tmp_path / "a.png", tmp_path, "deadbeef", 2)
    row.pop("path", None)

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root="",
        trust_manifest_input_root=True,
        manifest_input_root_allowlist=str(tmp_path),
        verify_sha1=False,
        fsync_interval=0,
        durability="none",
        resume=True,
        retry_errors=False,
        log_level="INFO",
        log_json=False,
        run_id="",
        generator_version="",
    )

    with pytest.raises(SystemExit, match="Failed to read manifest: manifest line 1 schema validation failed"):
        apply_changes.cmd_apply(args)


def test_apply_trust_manifest_root_requires_allowlist(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")
    sha1 = apply_changes.sha1_file(src)

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_row(src, input_root, sha1, 2)])

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root="",
        trust_manifest_input_root=True,
        manifest_input_root_allowlist="",
        verify_sha1=False,
        fsync_interval=0,
        durability="none",
        resume=True,
        retry_errors=False,
        log_level="INFO",
        log_json=False,
        run_id="",
        generator_version="",
    )

    with pytest.raises(
        SystemExit,
        match="--trust-manifest-input-root requires --manifest-input-root-allowlist",
    ):
        apply_changes.cmd_apply(args)


def test_apply_manifest_input_root_allowlist_parse_error(monkeypatch, tmp_path: Path):
    output_root = tmp_path / "output"
    output_root.mkdir()

    src = tmp_path / "a.png"
    src.write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_row(src, tmp_path, apply_changes.sha1_file(src), 2)])

    original_resolve = apply_changes.Path.resolve

    def fake_resolve(self):
        if str(self).endswith("bad_allowlist"):
            raise RuntimeError("allowlist bad")
        return original_resolve(self)

    monkeypatch.setattr(apply_changes.Path, "resolve", fake_resolve)

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root="",
        trust_manifest_input_root=True,
        manifest_input_root_allowlist="bad_allowlist",
        verify_sha1=False,
        fsync_interval=0,
        durability="none",
        resume=True,
        retry_errors=False,
        log_level="INFO",
        log_json=False,
        run_id="",
        generator_version="",
    )

    with pytest.raises(SystemExit, match="Failed to resolve manifest input-root allowlist: allowlist bad"):
        apply_changes.cmd_apply(args)


def test_apply_manifest_input_root_allowlist_rejects_system_root(tmp_path: Path):
    output_root = tmp_path / "output"
    output_root.mkdir()

    src = tmp_path / "a.png"
    src.write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_row(src, tmp_path, apply_changes.sha1_file(src), 2)])

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root="",
        trust_manifest_input_root=True,
        manifest_input_root_allowlist="/",
        verify_sha1=False,
        fsync_interval=0,
        durability="none",
        resume=True,
        retry_errors=False,
        log_level="INFO",
        log_json=False,
        run_id="",
        generator_version="",
    )

    with pytest.raises(SystemExit, match="Manifest input-root allowlist must not include the filesystem root"):
        apply_changes.cmd_apply(args)


def test_apply_input_root_rejects_system_root(tmp_path: Path):
    output_root = tmp_path / "output"
    output_root.mkdir()

    src = tmp_path / "a.png"
    src.write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_row(src, tmp_path, apply_changes.sha1_file(src), 2)])

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root="/",
        verify_sha1=False,
        fsync_interval=0,
        durability="none",
        resume=True,
        retry_errors=False,
        log_level="INFO",
        log_json=False,
        run_id="",
        generator_version="",
    )

    with pytest.raises(SystemExit, match="Input root must not be the filesystem root"):
        apply_changes.cmd_apply(args)


def test_rollback_overwrite_directory_uses_target_file_path(tmp_path: Path):
    moved = tmp_path / "moved.txt"
    moved.write_text("new", encoding="utf-8")

    dst_file_path = tmp_path / "origin.txt"
    dst_file_path.mkdir()

    manifest = tmp_path / "rollback_manifest.jsonl"
    manifest.write_text(
        json.dumps({"path": str(dst_file_path), "new_path": str(moved), "media_type": "image"}) + "\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(
        manifest=str(manifest),
        dry_run=False,
        overwrite=True,
        allowed_root=str(tmp_path),
    )
    apply_changes.cmd_rollback(args)

    assert dst_file_path.is_file()
    assert dst_file_path.read_text(encoding="utf-8") == "new"
    assert not moved.exists()
