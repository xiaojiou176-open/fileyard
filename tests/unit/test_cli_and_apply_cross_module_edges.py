import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import pytest

from apps.cli import cli_app
from packages.application import analyze_media, apply_changes


def test_cli_main_logs_config_warnings_and_errors(monkeypatch, tmp_path: Path):
    events = []

    def fake_log_event(_logger, _level, event, message, **fields):
        events.append((event, message, fields))

    monkeypatch.setattr(cli_app, "setup_logger", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(cli_app, "log_event", fake_log_event)
    monkeypatch.setattr(
        cli_app,
        "validate_config",
        lambda *_args, **_kwargs: (
            ["unknown warning"],
            ["Unknown config key: report.bad", "Invalid config value type: report.validate", "other error"],
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "report",
            "--manifest",
            str(tmp_path / "m.jsonl"),
            "--out",
            str(tmp_path / "r.json"),
        ],
    )

    with pytest.raises(SystemExit, match="Config validation failed"):
        cli_app.main()

    warning_events = [e for e in events if e[0] == "config_warning"]
    error_events = [e for e in events if e[0] == "config_error"]
    assert len(warning_events) == 1
    assert len(error_events) == 3
    assert error_events[0][2]["error_code"] == cli_app.ErrorCode.CONFIG_UNKNOWN_KEY.value
    assert error_events[1][2]["error_code"] == cli_app.ErrorCode.CONFIG_TYPE_INVALID.value
    assert error_events[2][2]["error_code"] == cli_app.ErrorCode.CONFIG_INVALID.value


def test_cli_main_lock_fail_exits(monkeypatch, tmp_path: Path):
    logs = []

    monkeypatch.setattr(cli_app, "validate_config", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr(cli_app, "setup_logger", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        cli_app,
        "log_event",
        lambda _logger, _level, event, _msg, **kwargs: logs.append((event, kwargs)),
    )
    monkeypatch.setattr(cli_app, "acquire_file_lock", lambda _path: (_ for _ in ()).throw(RuntimeError("lock boom")))
    monkeypatch.setattr(cli_app, "release_file_lock", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli_app, "cmd_report", lambda _args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "report",
            "--manifest",
            str(tmp_path / "m.jsonl"),
            "--out",
            str(tmp_path / "r.json"),
        ],
    )

    with pytest.raises(SystemExit, match="Failed to acquire task lock"):
        cli_app.main()

    assert any(event == "manifest_lock_fail" for event, _ in logs)


def test_apply_resolve_crash_inject_validation(monkeypatch):
    args = argparse.Namespace(crash_inject="after-move-before-manifest-commit")

    monkeypatch.setattr(apply_changes, "_is_test_hooks_enabled", lambda: False)
    with pytest.raises(SystemExit, match="crash_inject is available only in test mode"):
        apply_changes._resolve_apply_crash_inject(args)

    monkeypatch.setattr(apply_changes, "_is_test_hooks_enabled", lambda: True)
    args.crash_inject = "unknown-point"
    with pytest.raises(SystemExit, match="Unknown crash_inject"):
        apply_changes._resolve_apply_crash_inject(args)


def test_cmd_rollback_rejects_invalid_run_id(tmp_path: Path):
    manifest = tmp_path / "rollback.jsonl"
    manifest.write_text("", encoding="utf-8")

    args = argparse.Namespace(
        manifest=str(manifest),
        dry_run=True,
        overwrite=False,
        allowed_root=str(tmp_path),
        run_id="!!",
        strict_integrity=False,
    )

    with pytest.raises(SystemExit, match="Invalid run_id"):
        apply_changes.cmd_rollback(args)


def test_cmd_rollback_requires_allowed_root(tmp_path: Path):
    manifest = tmp_path / "rollback.jsonl"
    manifest.write_text("", encoding="utf-8")

    args = argparse.Namespace(
        manifest=str(manifest),
        dry_run=True,
        overwrite=False,
        allowed_root="",
        run_id="rollback-test-001",
        strict_integrity=False,
    )

    with pytest.raises(SystemExit, match="rollback requires --allowed-root"):
        apply_changes.cmd_rollback(args)


def test_cmd_rollback_manifest_read_fail(tmp_path: Path):
    manifest = tmp_path / "rollback.jsonl"
    manifest.write_text("{not-json}\n", encoding="utf-8")

    args = argparse.Namespace(
        manifest=str(manifest),
        dry_run=True,
        overwrite=False,
        allowed_root=str(tmp_path),
        run_id="rollback-test-002",
        strict_integrity=False,
    )

    with pytest.raises(ValueError, match="manifest line 1 JSON parse failed"):
        apply_changes.cmd_rollback(args)


def test_cmd_rollback_strict_integrity_requires_hmac_key(monkeypatch, tmp_path: Path):
    manifest = tmp_path / "rollback.jsonl"
    manifest.write_text("", encoding="utf-8")
    monkeypatch.delenv("MOVI_ROLLBACK_HMAC_KEY", raising=False)

    args = argparse.Namespace(
        manifest=str(manifest),
        dry_run=True,
        overwrite=False,
        allowed_root=str(tmp_path),
        run_id="rollback-test-003",
        strict_integrity=True,
    )

    with pytest.raises(SystemExit, match="strict_integrity=true requires MOVI_ROLLBACK_HMAC_KEY"):
        apply_changes.cmd_rollback(args)


def test_retry_cleanup_queue_rewrites_remaining_entries(monkeypatch, tmp_path: Path):
    queue = tmp_path / "cleanup_queue.jsonl"
    queue.write_text(
        "\n".join(
            [
                "",
                "not-json",
                json.dumps({"name": "file-a"}, ensure_ascii=False),
                json.dumps({"name": "file-b"}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    deleted = []

    def fake_safe_delete_file(_client, name, _logger, timeout_s):
        deleted.append((name, timeout_s))
        return name == "file-a"

    monkeypatch.setattr(analyze_media, "safe_delete_file", fake_safe_delete_file)

    pending, recovered = analyze_media._retry_cleanup_queue(
        cleanup_queue_path=queue,
        offline=False,
        get_client=lambda: object(),
        logger=logging.getLogger("test"),
        timeout_s=3.5,
        run_id="run-001",
    )

    assert pending == 2
    assert recovered == 1
    assert deleted == [("file-a", 3.5), ("file-b", 3.5)]
    remaining_lines = [line for line in queue.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(remaining_lines) == 1
    assert json.loads(remaining_lines[0])["name"] == "file-b"


def test_retry_cleanup_queue_unlinks_when_all_recovered(monkeypatch, tmp_path: Path):
    queue = tmp_path / "cleanup_queue.jsonl"
    queue.write_text(json.dumps({"name": "file-a"}, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *_args, **_kwargs: True)

    pending, recovered = analyze_media._retry_cleanup_queue(
        cleanup_queue_path=queue,
        offline=False,
        get_client=lambda: object(),
        logger=logging.getLogger("test"),
        timeout_s=2.0,
        run_id="run-002",
    )

    assert pending == 1
    assert recovered == 1
    assert not queue.exists()


def test_retry_cleanup_queue_logs_and_returns_on_exception(monkeypatch, tmp_path: Path):
    queue = tmp_path / "cleanup_queue.jsonl"
    queue.write_text(json.dumps({"name": "file-a"}, ensure_ascii=False) + "\n", encoding="utf-8")

    original_open = Path.open

    def fake_open(self, *args, **kwargs):
        if self == queue:
            raise RuntimeError("queue read failed")
        return original_open(self, *args, **kwargs)

    events = []

    monkeypatch.setattr(Path, "open", fake_open)
    monkeypatch.setattr(
        analyze_media,
        "log_event",
        lambda _logger, _level, event, _msg, **kwargs: events.append((event, kwargs)),
    )

    pending, recovered = analyze_media._retry_cleanup_queue(
        cleanup_queue_path=queue,
        offline=False,
        get_client=lambda: object(),
        logger=logging.getLogger("test"),
        timeout_s=1.0,
        run_id="run-003",
    )

    assert pending == 0
    assert recovered == 0
    assert any(event == "cleanup_queue_retry_fail" for event, _ in events)


def test_cleanup_orphaned_queues_scoped_and_age_based(tmp_path: Path):
    queue_root = tmp_path / "queues"
    queue_root.mkdir(parents=True, exist_ok=True)
    old_q = queue_root / "old.cleanup_uploads.jsonl"
    fresh_q = queue_root / "fresh.cleanup_uploads.jsonl"
    nested_dir = queue_root / "nested" / "deep"
    nested_dir.mkdir(parents=True, exist_ok=True)
    nested_old_q = nested_dir / "nested-old.cleanup_uploads.jsonl"
    nested_fresh_q = nested_dir / "nested-fresh.cleanup_uploads.jsonl"
    other = queue_root / "ignore.txt"
    old_q.write_text('{"name":"a"}\n', encoding="utf-8")
    fresh_q.write_text('{"name":"b"}\n', encoding="utf-8")
    nested_old_q.write_text('{"name":"c"}\n', encoding="utf-8")
    nested_fresh_q.write_text('{"name":"d"}\n', encoding="utf-8")
    other.write_text("x", encoding="utf-8")

    now = time.time()
    os.utime(old_q, (now - 48 * 3600, now - 48 * 3600))
    os.utime(fresh_q, (now, now))
    os.utime(nested_old_q, (now - 48 * 3600, now - 48 * 3600))
    os.utime(nested_fresh_q, (now, now))

    analyze_media._cleanup_orphaned_queues(queue_root, max_age_hours=24)

    assert not old_q.exists()
    assert fresh_q.exists()
    assert not nested_old_q.exists()
    assert nested_fresh_q.exists()
    assert other.exists()


def test_cleanup_orphaned_queues_unlinks_symlink_only(tmp_path: Path):
    queue_root = tmp_path / "queues"
    queue_root.mkdir(parents=True, exist_ok=True)
    outside_root = tmp_path / "outside"
    outside_root.mkdir(parents=True, exist_ok=True)

    target_file = outside_root / "target.cleanup_uploads.jsonl"
    link_file = queue_root / "link.cleanup_uploads.jsonl"
    target_file.write_text('{"name":"external"}\n', encoding="utf-8")
    os.symlink(target_file, link_file)

    now = time.time()
    os.utime(link_file, (now - 48 * 3600, now - 48 * 3600), follow_symlinks=False)

    analyze_media._cleanup_orphaned_queues(queue_root, max_age_hours=24)

    assert not link_file.exists()
    assert target_file.exists()


def test_retry_cleanup_queue_offline_skips_orphan_cleanup(monkeypatch, tmp_path: Path):
    queue_root = tmp_path / "queues"
    queue_root.mkdir(parents=True, exist_ok=True)
    old_q = queue_root / "old.cleanup_uploads.jsonl"
    active_q = queue_root / "active.cleanup_uploads.jsonl"
    old_q.write_text('{"name":"stale"}\n', encoding="utf-8")
    active_q.write_text('{"name":"active"}\n', encoding="utf-8")

    cleanup_called = False

    def fake_cleanup(*_args, **_kwargs):
        nonlocal cleanup_called
        cleanup_called = True

    monkeypatch.setattr(analyze_media, "_cleanup_orphaned_queues", fake_cleanup)

    pending, recovered = analyze_media._retry_cleanup_queue(
        cleanup_queue_path=active_q,
        offline=True,
        get_client=lambda: object(),
        logger=logging.getLogger("test"),
        timeout_s=1.0,
        run_id="run-offline-cleanup",
    )

    assert pending == 0
    assert recovered == 0
    assert cleanup_called
    assert old_q.exists()
    assert active_q.exists()


def test_retry_cleanup_queue_missing_file_skips_orphan_cleanup(monkeypatch, tmp_path: Path):
    queue = tmp_path / "missing.cleanup_uploads.jsonl"
    cleanup_called = False

    def fake_cleanup(*_args, **_kwargs):
        nonlocal cleanup_called
        cleanup_called = True

    monkeypatch.setattr(analyze_media, "_cleanup_orphaned_queues", fake_cleanup)

    pending, recovered = analyze_media._retry_cleanup_queue(
        cleanup_queue_path=queue,
        offline=False,
        get_client=lambda: object(),
        logger=logging.getLogger("test"),
        timeout_s=1.0,
        run_id="run-missing-cleanup",
    )

    assert pending == 0
    assert recovered == 0
    assert cleanup_called
