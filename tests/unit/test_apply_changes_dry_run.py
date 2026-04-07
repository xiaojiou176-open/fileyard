import argparse
from pathlib import Path

from packages.application.apply_changes import cmd_apply

from packages.domain.core_utils import sha1_file
from packages.infrastructure.manifest_store import read_jsonl_list, write_jsonl


def test_apply_dry_run_sets_new_path(tmp_path: Path):
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
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=True,
        fsync_interval=0,
    )

    cmd_apply(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0].get("new_path")
    assert src.exists()
