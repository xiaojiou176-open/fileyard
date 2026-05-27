import argparse
from pathlib import Path

from packages.application import apply_changes
from packages.domain.pipeline_config import RowStatus
from packages.infrastructure.manifest_store import write_jsonl


def _base_row(src: Path, input_root: Path, sha1: str):
    return {
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


def test_apply_retry_errors_clears_and_marks_skipped(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"data")
    sha1 = apply_changes.sha1_file(src)

    row = _base_row(src, input_root, sha1)
    row["error"] = "旧错误"
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
        retry_errors=True,
        log_level="INFO",
        log_json=False,
        run_id="",
        generator_version="",
    )

    apply_changes.cmd_apply(args)
    rows = list(apply_changes.read_jsonl(Path(manifest), validate=True))
    assert rows[0].get("error") == ""
    assert rows[0]["status"] == RowStatus.SKIPPED.value
    assert rows[0].get("new_path")


def test_apply_resume_skips_existing_new_path(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "b.png"
    src.write_bytes(b"data")
    sha1 = apply_changes.sha1_file(src)

    dst = output_root / "截图" / "工作" / "example.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"moved")

    row = _base_row(src, input_root, sha1)
    row["new_path"] = str(dst)
    row["status"] = RowStatus.APPLIED.value
    row["error"] = "stale error"
    row["error_code"] = "MOVE_FAIL"
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
        verify_sha1=False,
        fsync_interval=0,
        durability="none",
        resume=True,
        retry_errors=True,
        log_level="INFO",
        log_json=False,
        run_id="",
        generator_version="",
    )

    apply_changes.cmd_apply(args)
    rows = list(apply_changes.read_jsonl(Path(manifest), validate=True))
    assert rows[0]["status"] == RowStatus.APPLIED.value
    assert rows[0].get("error") == ""
    assert not rows[0].get("error_code")
