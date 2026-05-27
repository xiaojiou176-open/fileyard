import argparse
from pathlib import Path

import pytest

from packages.application import apply_changes
from packages.domain.pipeline_config import KEY_ERROR_CODE, ErrorCode
from packages.infrastructure.manifest_store import read_jsonl_list, write_jsonl


def _apply_args(manifest: Path, input_root: str, output_root: Path, **extra):
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
        run_id="apply_f_001",
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


def _row(src: Path, input_root: Path) -> dict:
    digest = apply_changes.sha1_file(src)
    return {
        "path": str(src),
        "input_root": str(input_root),
        "sha1": digest,
        "hash8": digest[:8],
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


def test_helper_paths_and_jsonl_validation(tmp_path: Path, monkeypatch):
    backup_target = tmp_path / "target.txt"
    backup_target.write_text("x", encoding="utf-8")
    first_candidate = backup_target.with_name(f"{backup_target.name}.overwrite-backup-20250101T000000Z")
    first_candidate.write_text("existing", encoding="utf-8")

    class _FakeNow:
        def strftime(self, _fmt):
            return "20250101T000000Z"

    class _FakeDatetime:
        @staticmethod
        def now(_tz):
            return _FakeNow()

    monkeypatch.setattr(apply_changes.dt, "datetime", _FakeDatetime)
    next_path = apply_changes._next_overwrite_backup_path(backup_target)
    assert next_path.name.endswith("-1")

    crash_file = tmp_path / "manifest.partial"
    crash_file.write_text("payload", encoding="utf-8")
    existing_crash = crash_file.with_name(f"{crash_file.name}.crash-20250101T000000Z")
    existing_crash.write_text("old", encoding="utf-8")
    preserved = apply_changes._preserve_crash_file(crash_file)
    assert preserved.name.endswith("-1")
    assert preserved.exists()

    assert apply_changes._is_valid_jsonl_file(tmp_path / "missing.jsonl") is False

    bad_jsonl = tmp_path / "bad.jsonl"
    bad_jsonl.write_text("not-json\n", encoding="utf-8")
    assert apply_changes._is_valid_jsonl_file(bad_jsonl) is False


def test_resolve_apply_crash_inject_branches(monkeypatch):
    monkeypatch.setattr(apply_changes, "_is_test_hooks_enabled", lambda: False)
    with pytest.raises(SystemExit, match="crash_inject is available only in test mode"):
        apply_changes._resolve_apply_crash_inject(argparse.Namespace(crash_inject="after-move-before-manifest-commit"))

    monkeypatch.setattr(apply_changes, "_is_test_hooks_enabled", lambda: True)
    with pytest.raises(SystemExit, match="Unknown crash_inject"):
        apply_changes._resolve_apply_crash_inject(argparse.Namespace(crash_inject="unknown-point"))


def test_cmd_apply_invalid_run_id_exits(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    src = input_root / "a.png"
    src.write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_row(src, input_root)])

    with pytest.raises(SystemExit, match="Invalid run_id"):
        apply_changes.cmd_apply(_apply_args(manifest, str(input_root), output_root, run_id="bad run id"))


def test_cmd_apply_manifest_row_invalid_and_existing_error(tmp_path: Path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")
    row_error = _row(src, input_root)
    row_error["error"] = "already-bad"
    invalid_row = {"media_type": "image", "ai": {}}

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row_error])

    captured_rows: list[dict] = []

    def _iter_chunks(_path, validate=True, chunk_size=1000):
        yield [invalid_row, row_error]

    def _capture_write(_fh, item, fsync=False):
        captured_rows.append(dict(item))

    monkeypatch.setattr(apply_changes, "iter_jsonl_chunks", _iter_chunks)
    monkeypatch.setattr(apply_changes, "write_jsonl_line", _capture_write)
    apply_changes.cmd_apply(_apply_args(manifest, str(input_root), output_root, retry_errors=False))

    assert captured_rows[0][KEY_ERROR_CODE] == ErrorCode.MANIFEST_ROW_INVALID.value
    assert captured_rows[1]["status"] == "error"
    assert captured_rows[1]["status_reason"] == "existing_error"


def test_cmd_apply_resume_verify_sha1_fail_and_mismatch(tmp_path: Path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()

    resumed_1 = output_root / "a.done"
    resumed_2 = output_root / "b.done"
    resumed_1.write_bytes(b"a")
    resumed_2.write_bytes(b"b")

    src1 = input_root / "source-a.png"
    src2 = input_root / "source-b.png"
    src1.write_bytes(b"1")
    src2.write_bytes(b"2")

    row1 = _row(src1, input_root)
    row1["new_path"] = str(resumed_1)
    row1["sha1"] = "abc"

    row2 = _row(src2, input_root)
    row2["new_path"] = str(resumed_2)
    row2["sha1"] = "expected"

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row1, row2])

    original_sha1 = apply_changes.sha1_file

    def _sha1_side_effect(path: Path):
        if path == resumed_1:
            raise RuntimeError("hash fail")
        if path == resumed_2:
            return "different"
        return original_sha1(path)

    monkeypatch.setattr(apply_changes, "sha1_file", _sha1_side_effect)

    apply_changes.cmd_apply(_apply_args(manifest, str(input_root), output_root, verify_sha1=True, resume=True))
    out_rows = read_jsonl_list(manifest, validate=True)
    assert out_rows[0][KEY_ERROR_CODE] == ErrorCode.HASH_FAIL.value
    assert out_rows[1][KEY_ERROR_CODE] == ErrorCode.HASH_MISMATCH.value


def test_cmd_apply_manifest_input_root_allowlist_rejects_row(tmp_path: Path):
    outside_root = tmp_path / "outside"
    output_root = tmp_path / "output"
    allowed = tmp_path / "allowed"
    outside_root.mkdir()
    output_root.mkdir()
    allowed.mkdir()

    src = outside_root / "orphan.png"
    src.write_bytes(b"x")
    row = _row(src, outside_root)

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

    apply_changes.cmd_apply(
        _apply_args(
            manifest,
            "",
            output_root,
            trust_manifest_input_root=True,
            manifest_input_root_allowlist=str(allowed),
            resume=False,
        )
    )

    out_rows = read_jsonl_list(manifest, validate=True)
    assert out_rows[0][KEY_ERROR_CODE] == ErrorCode.INPUT_ROOT_INVALID.value
    assert "outside the allowlist" in (out_rows[0].get("error") or "")


def test_cmd_rollback_row_skipped_under_strict_integrity_without_run_metadata(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FILEORGANIZE_ROLLBACK_HMAC_KEY", "f-shard-key")

    src = tmp_path / "moved.txt"
    dst = tmp_path / "origin.txt"
    src.write_text("payload", encoding="utf-8")

    manifest = tmp_path / "rollback_manifest.jsonl"
    write_jsonl(manifest, [{"path": str(dst), "new_path": str(src), "media_type": "image"}])

    with pytest.raises(SystemExit, match="strict_integrity validation failed: rollback candidates exist but all are invalid"):
        apply_changes.cmd_rollback(
            argparse.Namespace(
                manifest=str(manifest),
                dry_run=False,
                overwrite=False,
                allowed_root=str(tmp_path),
                strict_integrity=True,
                log_level="INFO",
                log_json=False,
                run_id="rollback_f_001",
            )
        )

    assert not dst.exists()
    assert src.exists()


def test_cmd_rollback_removed_legacy_flag_is_ignored(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FILEORGANIZE_ROLLBACK_HMAC_KEY", "f-shard-key")
    manifest = tmp_path / "rollback_manifest.jsonl"
    write_jsonl(manifest, [])

    events: list[str] = []
    original_log_event = apply_changes.log_event

    def _capture(logger, level, event, message, **fields):
        events.append(event)
        return original_log_event(logger, level, event, message, **fields)

    monkeypatch.setattr(apply_changes, "log_event", _capture)

    base_args = dict(
        manifest=str(manifest),
        dry_run=True,
        overwrite=False,
        allowed_root=str(tmp_path),
        strict_integrity=False,
        log_level="INFO",
        log_json=False,
        run_id="rollback_f_legacy_removed",
    )

    apply_changes.cmd_rollback(argparse.Namespace(**base_args))
    events_without_legacy = events.copy()
    events.clear()

    apply_changes.cmd_rollback(argparse.Namespace(**base_args, allow_legacy_manifest=True))
    assert events == events_without_legacy


def test_cmd_rollback_overwrite_cleanup_and_restore_failure_events(tmp_path: Path, monkeypatch):
    src_ok = tmp_path / "moved-ok.txt"
    dst_ok = tmp_path / "orig-ok.txt"
    src_ok.write_text("new-ok", encoding="utf-8")
    dst_ok.write_text("old-ok", encoding="utf-8")

    src_fail = tmp_path / "moved-fail.txt"
    dst_fail = tmp_path / "orig-fail.txt"
    src_fail.write_text("new-fail", encoding="utf-8")
    dst_fail.write_text("old-fail", encoding="utf-8")

    manifest = tmp_path / "rollback_manifest.jsonl"
    write_jsonl(
        manifest,
        [
            {"path": str(dst_ok), "new_path": str(src_ok), "media_type": "image"},
            {"path": str(dst_fail), "new_path": str(src_fail), "media_type": "image"},
        ],
    )

    events = []
    original_log_event = apply_changes.log_event

    def _capture(logger, level, event, message, **fields):
        events.append(event)
        return original_log_event(logger, level, event, message, **fields)

    monkeypatch.setattr(apply_changes, "log_event", _capture)

    original_replace = apply_changes.Path.replace
    original_unlink = apply_changes.Path.unlink

    def _replace(self, target):
        self_name = str(self)
        target_name = str(target)
        if self_name.endswith("moved-fail.txt") and target_name.endswith("orig-fail.txt"):
            raise RuntimeError("move failed")
        if ".overwrite-backup-" in self_name and target_name.endswith("orig-fail.txt"):
            raise RuntimeError("restore backup failed")
        return original_replace(self, target)

    def _unlink(self, missing_ok=False):
        if ".overwrite-backup-" in str(self):
            raise RuntimeError("cannot cleanup backup")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(apply_changes.Path, "replace", _replace)
    monkeypatch.setattr(apply_changes.Path, "unlink", _unlink)

    apply_changes.cmd_rollback(
        argparse.Namespace(
            manifest=str(manifest),
            dry_run=False,
            overwrite=True,
            allowed_root=str(tmp_path),
            strict_integrity=False,
            log_level="INFO",
            log_json=False,
            run_id="rollback_f_002",
        )
    )

    assert "rollback_overwrite_backup_preserved" in events
    assert "rollback_overwrite_restore_fail" in events
    assert "rollback_fail" in events
    assert dst_ok.read_text(encoding="utf-8") == "new-ok"


def test_cmd_rollback_allowed_root_required_and_manifest_read_fail(tmp_path: Path, monkeypatch):
    manifest = tmp_path / "rollback_manifest.jsonl"
    write_jsonl(manifest, [{"path": "a", "new_path": "b", "media_type": "image"}])

    with pytest.raises(SystemExit, match="rollback requires --allowed-root"):
        apply_changes.cmd_rollback(
            argparse.Namespace(
                manifest=str(manifest),
                dry_run=False,
                overwrite=False,
                allowed_root="",
                strict_integrity=False,
                log_level="INFO",
                log_json=False,
                run_id="rollback_f_003",
            )
        )

    bad_manifest = tmp_path / "bad_manifest.jsonl"
    bad_manifest.write_text("[]\n", encoding="utf-8")

    def _raise_read(*_args, **_kwargs):
        raise ValueError("broken manifest")

    monkeypatch.setattr(apply_changes, "read_jsonl", _raise_read)
    with pytest.raises(SystemExit, match="Failed to read manifest"):
        apply_changes.cmd_rollback(
            argparse.Namespace(
                manifest=str(bad_manifest),
                dry_run=False,
                overwrite=False,
                allowed_root=str(tmp_path),
                strict_integrity=False,
                log_level="INFO",
                log_json=False,
                run_id="rollback_f_004",
            )
        )
