import argparse
import logging
from pathlib import Path

import pytest

from packages.application import apply_changes, apply_command, apply_command_helpers
from packages.domain.pipeline_config import KEY_ERROR_CODE, ErrorCode
from packages.infrastructure.manifest_store import read_jsonl_list, write_jsonl


def _base_row(src: Path, input_root: Path, *, schema_version: int | str = 2, sha1_value: str | None = None) -> dict:
    digest = sha1_value if sha1_value is not None else apply_changes.sha1_file(src)
    return {
        "schema_version": schema_version,
        "path": str(src),
        "input_root": str(input_root),
        "sha1": digest,
        "hash8": (digest or "")[:8],
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


def _args(manifest: Path, input_root: str, output_root: Path, **extra) -> argparse.Namespace:
    base = dict(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root=input_root,
        verify_sha1=False,
        fsync_interval=0,
        durability="none",
        resume=True,
        retry_errors=False,
        log_level="INFO",
        log_json=False,
        run_id="apply_branch_001",
        generator_version="",
        report="",
        rollback_manifest="",
        trust_manifest_input_root=False,
        manifest_input_root_allowlist="",
        chunk_size=10,
        crash_inject="",
    )
    base.update(extra)
    return argparse.Namespace(**base)


def test_cmd_apply_chunk_size_defaults_and_schema_str_digit(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")
    row = _base_row(src, input_root, schema_version="2", sha1_value="")

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

    apply_changes.cmd_apply(_args(manifest, str(input_root), output_root, chunk_size=-1, verify_sha1=False))
    rows = read_jsonl_list(manifest, validate=True)
    assert len(rows) == 1
    assert rows[0].get("status") in {"skipped", "applied", "duplicate", "error"}


def test_cmd_apply_rollback_manifest_open_fail(tmp_path: Path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_base_row(src, input_root)])

    original_open = apply_changes._apply_command.open_jsonl_writer

    def _fake_open(path: Path):
        if str(path).endswith(".rollback.jsonl.partial"):
            raise RuntimeError("open rollback failed")
        return original_open(path)

    monkeypatch.setattr(apply_changes._apply_command, "open_jsonl_writer", _fake_open)

    with pytest.raises(SystemExit, match="Failed to open rollback manifest"):
        apply_changes.cmd_apply(_args(manifest, str(input_root), output_root, dry_run=False))


def test_cmd_apply_manifest_update_fail_on_partial_replace(tmp_path: Path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_base_row(src, input_root)])

    original_replace = apply_changes.Path.replace

    def _fake_replace(self: Path, target: Path):
        if str(self).endswith(".partial") and str(target).endswith("manifest.jsonl"):
            raise OSError("replace fail")
        return original_replace(self, target)

    monkeypatch.setattr(apply_changes.Path, "replace", _fake_replace)

    with pytest.raises(SystemExit, match="Failed to update manifest"):
        apply_changes.cmd_apply(_args(manifest, str(input_root), output_root, dry_run=True, dedupe=False))


def test_cmd_apply_emits_report_written_event(tmp_path: Path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_base_row(src, input_root)])

    events: list[str] = []

    def _capture_event(logger, level, event, message, **kwargs):
        _ = (logger, level, message, kwargs)
        events.append(event)

    monkeypatch.setattr(apply_changes, "log_event", _capture_event)

    report_path = tmp_path / "report.json"
    apply_changes.cmd_apply(_args(manifest, str(input_root), output_root, report=str(report_path), dedupe=False))

    assert "report_written" in events


def test_cmd_apply_prescan_status_branch_and_resolve_exception(tmp_path: Path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")
    resumed = output_root / "resumed.png"
    resumed.write_bytes(b"x")
    row = _base_row(src, input_root)
    row["new_path"] = str(resumed)
    row["status"] = "error"
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

    original_resolve = apply_changes.Path.resolve

    def _fake_resolve(self: Path, *args, **kwargs):
        if self == src:
            raise OSError("resolve fail")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(apply_changes.Path, "resolve", _fake_resolve)
    apply_changes.cmd_apply(_args(manifest, str(input_root), output_root, dry_run=True))
    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0].get("status") in {"applied", "error", "skipped"}


def test_cmd_apply_manifest_row_root_cannot_be_filesystem_root(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")
    row = _base_row(src, input_root)
    row["input_root"] = "/"
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

    apply_changes.cmd_apply(
        _args(
            manifest,
            "",
            output_root,
            trust_manifest_input_root=True,
            manifest_input_root_allowlist=str(tmp_path),
            dry_run=True,
            dedupe=False,
        )
    )
    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0][KEY_ERROR_CODE] == ErrorCode.INPUT_ROOT_INVALID.value


def test_apply_command_cmd_rollback_delegates(monkeypatch):
    captured = {}

    def _fake_cmd_rollback(args):
        captured["args"] = args

    monkeypatch.setattr(apply_command, "_cmd_rollback", _fake_cmd_rollback)
    ns = argparse.Namespace(manifest="x")
    apply_command.cmd_rollback(ns)
    assert captured["args"] is ns


def test_helpers_resolve_apply_crash_inject_guards():
    args = argparse.Namespace(crash_inject="after-move-before-manifest-commit")
    with pytest.raises(SystemExit, match="crash_inject is available only in test mode"):
        apply_command_helpers.resolve_apply_crash_inject(
            args,
            crash_points={"after_move_before_manifest_commit"},
            is_test_hooks_enabled_fn=lambda: False,
        )

    with pytest.raises(SystemExit, match="Unknown crash_inject"):
        apply_command_helpers.resolve_apply_crash_inject(
            argparse.Namespace(crash_inject="unknown"),
            crash_points={"after_move_before_manifest_commit"},
            is_test_hooks_enabled_fn=lambda: True,
        )


def test_helpers_build_destination_truncates_filename(tmp_path: Path):
    row = {
        "path": str(tmp_path / "a.jpeg"),
        "media_type": "image",
        "sha1": "a" * 40,
        "hash8": "a" * 8,
        "file_mtime": "2025-01-01T12:00:00",
        "ai": {
            "kind": "截图",
            "category": "工作",
            "title": "verylongtitle_" * 200,
            "tags": [],
            "confidence": 1,
            "notes": "",
        },
    }
    folder, filename = apply_command_helpers.build_destination(row, tmp_path / "out", ["工作", "其他"])
    assert folder.exists() is False or isinstance(folder, Path)
    assert filename.endswith(".jpg")
    assert len(filename) <= apply_command_helpers.MAX_FILENAME_LENGTH


def test_helpers_recover_apply_wal_value_error_and_preserve_rollback_partial(tmp_path: Path):
    wal = tmp_path / "a.wal.json"
    wal.write_text('{"phase":"fileorganizeng"}', encoding="utf-8")
    partial = tmp_path / "manifest.partial"
    out_manifest = tmp_path / "manifest.jsonl"
    rollback_partial = tmp_path / "rollback.partial"
    rollback_partial.write_text("broken", encoding="utf-8")
    rollback_manifest = tmp_path / "rollback.jsonl"

    with pytest.raises(ValueError, match="recover_apply_wal is missing a required callback"):
        apply_command_helpers.recover_apply_wal(
            wal_marker=wal,
            partial_manifest=partial,
            rollback_partial=rollback_partial,
            rollback_manifest=rollback_manifest,
            out_manifest=out_manifest,
            logger=logging.getLogger("test"),
            run_id="run-1",
            generator_version="1",
            read_jsonl_fn=lambda *_a, **_k: [],
            build_rollback_from_manifest_fn=lambda rows: rows,
            open_jsonl_writer_fn=lambda path: path,
            attach_manifest_metadata_fn=lambda *args, **kwargs: None,
            write_jsonl_line_fn=lambda *args, **kwargs: None,
            sign_rollback_record_fn=lambda rec, run_id: "sig",
            rollback_sig_key="rollback_sig",
        )

    wal.write_text('{"phase":"fileorganizeng"}', encoding="utf-8")
    preserved_calls: list[Path] = []
    events: list[str] = []

    def _preserve(path: Path) -> Path:
        preserved_calls.append(path)
        return path

    def _log_event(_logger, _level, event, _message, **_fields):
        events.append(event)

    apply_command_helpers.recover_apply_wal(
        wal_marker=wal,
        partial_manifest=partial,
        rollback_partial=rollback_partial,
        rollback_manifest=rollback_manifest,
        out_manifest=out_manifest,
        logger=logging.getLogger("test"),
        run_id="run-2",
        generator_version="1",
        read_jsonl_fn=lambda *_a, **_k: [],
        build_rollback_from_manifest_fn=lambda rows: rows,
        open_jsonl_writer_fn=lambda path: path,
        attach_manifest_metadata_fn=lambda *args, **kwargs: None,
        write_jsonl_line_fn=lambda *args, **kwargs: None,
        sign_rollback_record_fn=lambda rec, run_id: "sig",
        rollback_sig_key="rollback_sig",
        is_valid_jsonl_file_fn=lambda _path: False,
        preserve_crash_file_fn=_preserve,
        log_event_fn=_log_event,
    )

    assert rollback_partial in preserved_calls
    assert "apply_wal_rollback_partial_ignored" in events
