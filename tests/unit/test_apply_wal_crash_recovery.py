import argparse
import json
from pathlib import Path

import pytest

from packages.application import apply_changes
from packages.infrastructure.manifest_store import read_jsonl_list, write_jsonl


def _prepare_manifest(tmp_path: Path) -> tuple[Path, Path, Path]:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    src = input_root / "sample.png"
    src.write_bytes(b"wal-crash")
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
    return manifest, input_root, output_root


def _apply_args(
    manifest: Path,
    input_root: Path,
    output_root: Path,
    crash_inject: str = "",
    dry_run: bool = False,
):
    return argparse.Namespace(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=dry_run,
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
        crash_inject=crash_inject,
    )


def _assert_recovered_state(manifest: Path, output_root: Path):
    rows = read_jsonl_list(manifest, validate=True)
    assert len(rows) == 1
    assert rows[0].get("status") == "applied"
    assert rows[0].get("new_path")
    moved = Path(rows[0]["new_path"])
    assert moved.exists()
    assert moved.is_file()
    assert (manifest.parent / "manifest.jsonl.rollback.jsonl").exists()
    assert not (manifest.parent / "manifest.jsonl.apply.wal.json").exists()
    assert str(moved).startswith(str(output_root))


def test_apply_crash_after_move_before_manifest_commit_is_recoverable(tmp_path: Path):
    manifest, input_root, output_root = _prepare_manifest(tmp_path)
    crash_args = _apply_args(
        manifest,
        input_root,
        output_root,
        crash_inject="after_move_before_manifest_commit",
    )
    with pytest.raises(RuntimeError, match="after_move_before_manifest_commit"):
        apply_changes.cmd_apply(crash_args)

    assert (manifest.parent / "manifest.jsonl.partial").exists()
    assert (manifest.parent / "manifest.jsonl.rollback.jsonl.partial").exists()
    assert (manifest.parent / "manifest.jsonl.apply.wal.json").exists()

    apply_changes.cmd_apply(_apply_args(manifest, input_root, output_root))
    _assert_recovered_state(manifest, output_root)


def test_apply_crash_after_manifest_before_rollback_commit_is_recoverable(tmp_path: Path):
    manifest, input_root, output_root = _prepare_manifest(tmp_path)
    crash_args = _apply_args(
        manifest,
        input_root,
        output_root,
        crash_inject="after_manifest_before_rollback_commit",
    )
    with pytest.raises(RuntimeError, match="after_manifest_before_rollback_commit"):
        apply_changes.cmd_apply(crash_args)

    assert not (manifest.parent / "manifest.jsonl.partial").exists()
    assert (manifest.parent / "manifest.jsonl.rollback.jsonl.partial").exists()
    assert (manifest.parent / "manifest.jsonl.apply.wal.json").exists()

    apply_changes.cmd_apply(_apply_args(manifest, input_root, output_root))
    _assert_recovered_state(manifest, output_root)


def test_apply_crash_after_rollback_before_finalize_is_recoverable(tmp_path: Path):
    manifest, input_root, output_root = _prepare_manifest(tmp_path)
    crash_args = _apply_args(
        manifest,
        input_root,
        output_root,
        crash_inject="after_rollback_before_finalize",
    )
    with pytest.raises(RuntimeError, match="after_rollback_before_finalize"):
        apply_changes.cmd_apply(crash_args)

    assert (manifest.parent / "manifest.jsonl.rollback.jsonl").exists()
    assert (manifest.parent / "manifest.jsonl.apply.wal.json").exists()

    apply_changes.cmd_apply(_apply_args(manifest, input_root, output_root))
    _assert_recovered_state(manifest, output_root)


def test_apply_wal_moving_phase_does_not_promote_broken_partial(tmp_path: Path):
    manifest, input_root, output_root = _prepare_manifest(tmp_path)
    partial_manifest = Path(str(manifest) + ".partial")
    partial_manifest.write_text("{broken jsonl", encoding="utf-8")
    wal = Path(str(manifest) + ".apply.wal.json")
    wal.write_text('{"phase":"moving"}', encoding="utf-8")

    apply_changes.cmd_apply(_apply_args(manifest, input_root, output_root, dry_run=True))

    rows = read_jsonl_list(manifest, validate=True)
    assert len(rows) == 1
    assert not wal.exists()
    assert list(tmp_path.glob("manifest.jsonl.partial.crash-*"))


def test_apply_rebuilds_rollback_manifest_when_wal_manifest_committed_and_partial_missing(
    tmp_path: Path,
):
    manifest, input_root, output_root = _prepare_manifest(tmp_path)
    rows = read_jsonl_list(manifest, validate=True)
    assert len(rows) == 1

    row = rows[0]
    src = Path(row["path"])
    moved = output_root / "recovered.png"
    src.replace(moved)
    row["new_path"] = str(moved)
    row["status"] = "applied"
    write_jsonl(manifest, [row])

    rollback_manifest = manifest.parent / "manifest.jsonl.rollback.jsonl"
    rollback_partial = Path(str(rollback_manifest) + ".partial")
    wal_file = Path(str(manifest) + ".apply.wal.json")
    wal_file.write_text(json.dumps({"phase": "manifest_committed"}), encoding="utf-8")

    args = _apply_args(manifest, input_root, output_root)
    args.input_root = ""
    with pytest.raises(
        SystemExit,
        match="apply requires --input-root; to trust manifest input_root values, explicitly set --trust-manifest-input-root",
    ):
        apply_changes.cmd_apply(args)

    assert not wal_file.exists()
    assert rollback_manifest.exists()
    assert not rollback_partial.exists()

    rollback_rows = read_jsonl_list(rollback_manifest, validate=True)
    assert len(rollback_rows) == 1
    assert rollback_rows[0].get("path") == str(src)
    assert rollback_rows[0].get("new_path") == str(moved)
    assert rollback_rows[0].get("status") == "applied"
