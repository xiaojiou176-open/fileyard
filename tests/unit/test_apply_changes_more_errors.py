import argparse
from pathlib import Path

import pytest

from packages.application import apply_changes
from packages.infrastructure.manifest_store import write_jsonl


def test_cmd_apply_output_root_file(tmp_path: Path):
    input_root = tmp_path / "input"
    input_root.mkdir()

    output_root = tmp_path / "output"
    output_root.write_text("file", encoding="utf-8")

    row = {
        "path": str(input_root / "a.png"),
        "input_root": str(input_root),
        "sha1": "",
        "hash8": "",
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
    )

    with pytest.raises(SystemExit):
        apply_changes.cmd_apply(args)


def test_cmd_apply_input_root_resolve_error(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "badroot"
    input_root.mkdir()
    output_root = tmp_path / "output"
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"data")

    row = {
        "path": str(src),
        "input_root": str(input_root),
        "sha1": "",
        "hash8": "",
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

    original_resolve = apply_changes.Path.resolve

    def fake_resolve(self):
        if str(self).endswith("badroot"):
            raise RuntimeError("resolve")
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
        manifest_input_root_allowlist=str(tmp_path),
        verify_sha1=False,
        fsync_interval=0,
    )

    apply_changes.cmd_apply(args)
    rows = list(apply_changes.read_jsonl(Path(manifest), validate=True))
    assert "input root validation failed" in (rows[0].get("error") or "")


def test_cmd_apply_missing_sha1(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    input_root.mkdir()
    output_root = tmp_path / "output"
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"data")

    row = {
        "path": str(src),
        "input_root": str(input_root),
        "sha1": "",
        "hash8": "",
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

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=True,
        fsync_interval=0,
    )

    apply_changes.cmd_apply(args)
    rows = list(apply_changes.read_jsonl(Path(manifest), validate=True))
    assert "missing sha1" in (rows[0].get("error") or "")


def test_cmd_apply_sha1_exception(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    input_root.mkdir()
    output_root = tmp_path / "output"
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"data")

    row = {
        "path": str(src),
        "input_root": str(input_root),
        "sha1": "abc",
        "hash8": "abc",
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

    monkeypatch.setattr(apply_changes, "sha1_file", lambda *_: (_ for _ in ()).throw(RuntimeError("sha1")))

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=True,
        fsync_interval=0,
    )

    apply_changes.cmd_apply(args)
    rows = list(apply_changes.read_jsonl(Path(manifest), validate=True))
    assert "sha1 verification failed" in (rows[0].get("error") or "")


def test_cmd_apply_dedupe_move_error(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    a = input_root / "a.png"
    b = input_root / "b.png"
    a.write_bytes(b"same")
    b.write_bytes(b"same")

    sha1 = apply_changes.sha1_file(a)

    row_a = {
        "path": str(a),
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
    row_b = dict(row_a)
    row_b["path"] = str(b)

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row_a, row_b])

    move_calls = {"count": 0}

    def fake_move(*_):
        move_calls["count"] += 1
        if move_calls["count"] == 1:
            return str(output_root / "moved.png")
        raise RuntimeError("move")

    monkeypatch.setattr(apply_changes.shutil, "move", fake_move)

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

    apply_changes.cmd_apply(args)
    rows = list(apply_changes.read_jsonl(Path(manifest), validate=True))
    assert "dedupe move error" in (rows[1].get("error") or "")


def test_cmd_apply_build_destination_error(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"data")

    row = {
        "path": str(src),
        "input_root": str(input_root),
        "sha1": apply_changes.sha1_file(src),
        "hash8": "abcd",
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

    monkeypatch.setattr(
        apply_changes,
        "build_destination",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("path")),
    )

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=True,
        fsync_interval=0,
    )

    apply_changes.cmd_apply(args)
    rows = list(apply_changes.read_jsonl(Path(manifest), validate=True))
    assert "destination path error" in (rows[0].get("error") or "")


def test_cmd_apply_move_error(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"data")

    row = {
        "path": str(src),
        "input_root": str(input_root),
        "sha1": apply_changes.sha1_file(src),
        "hash8": "abcd",
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

    monkeypatch.setattr(apply_changes.shutil, "move", lambda *_: (_ for _ in ()).throw(RuntimeError("move")))

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

    apply_changes.cmd_apply(args)
    rows = list(apply_changes.read_jsonl(Path(manifest), validate=True))
    assert "move error" in (rows[0].get("error") or "")


def test_cmd_apply_replace_error(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"data")

    row = {
        "path": str(src),
        "input_root": str(input_root),
        "sha1": apply_changes.sha1_file(src),
        "hash8": "abcd",
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

    def fake_replace(self, target):
        raise RuntimeError("replace")

    monkeypatch.setattr(apply_changes.Path, "replace", fake_replace)

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=True,
        fsync_interval=0,
    )

    with pytest.raises(SystemExit):
        apply_changes.cmd_apply(args)

    monkeypatch.setattr(apply_changes.Path, "replace", original_replace)
