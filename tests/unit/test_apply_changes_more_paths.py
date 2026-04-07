import argparse
from pathlib import Path

from packages.application import apply_changes
from packages.domain.core_utils import sha1_file
from packages.infrastructure.manifest_store import read_jsonl_list, write_jsonl


def _row(path: Path, input_root: Path):
    sha1 = sha1_file(path)
    return {
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
            "confidence": 0.9,
            "notes": "",
        },
        "error": "",
    }


def test_cmd_apply_missing_source(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    missing = input_root / "missing.png"
    row = {
        "path": str(missing),
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
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=False,
        fsync_interval=0,
    )

    apply_changes.cmd_apply(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert "source file does not exist" in (rows[0].get("error") or "")


def test_cmd_apply_uses_manifest_input_root(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"data")

    row = _row(src, input_root)
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
        verify_sha1=True,
        fsync_interval=0,
    )

    apply_changes.cmd_apply(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0].get("new_path")


def test_cmd_apply_fsync_interval(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src1 = input_root / "a.png"
    src2 = input_root / "b.png"
    src1.write_bytes(b"data1")
    src2.write_bytes(b"data2")

    row1 = _row(src1, input_root)
    row2 = _row(src2, input_root)

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row1, row2])

    flags = []

    def fake_write_jsonl_line(fh, row, fsync=False):
        flags.append(fsync)

    monkeypatch.setattr(apply_changes, "write_jsonl_line", fake_write_jsonl_line)

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=True,
        fsync_interval=2,
    )

    apply_changes.cmd_apply(args)
    assert flags == [False, True]


def test_cmd_apply_out_manifest(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"data")

    row = _row(src, input_root)
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

    out_manifest = tmp_path / "out_manifest.jsonl"

    args = argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest=str(out_manifest),
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=True,
        fsync_interval=0,
    )

    apply_changes.cmd_apply(args)
    assert out_manifest.exists()
