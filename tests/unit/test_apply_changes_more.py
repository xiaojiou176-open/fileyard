import argparse
from pathlib import Path

from packages.application.apply_changes import cmd_apply

from packages.domain.core_utils import sha1_file
from packages.infrastructure.manifest_store import read_jsonl_list, write_jsonl


def _row_for(path: Path, input_root: Path, sha1: str):
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


def test_apply_rejects_outside_input_root(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"data")

    sha1 = sha1_file(outside)
    row = _row_for(outside, input_root, sha1)

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

    cmd_apply(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert "source file is outside the input root" in (rows[0].get("error") or "")


def test_apply_rejects_sha1_mismatch(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"data")

    row = _row_for(src, input_root, sha1="deadbeef")

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

    cmd_apply(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert "sha1 mismatch" in (rows[0].get("error") or "")


def test_apply_dedupe_moves_duplicates(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    a = input_root / "a.png"
    b = input_root / "b.png"
    a.write_bytes(b"same")
    b.write_bytes(b"same")

    sha1 = sha1_file(a)
    row_a = _row_for(a, input_root, sha1)
    row_b = _row_for(b, input_root, sha1)

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row_a, row_b])

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
    assert rows[1].get("new_path")
    assert rows[1].get("dedupe_of")
    dup_path = Path(rows[1]["new_path"])
    assert "duplicates" in dup_path.parts
    assert dup_path.exists()
