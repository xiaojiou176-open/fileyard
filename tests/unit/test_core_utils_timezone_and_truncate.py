import datetime as dt
import json
import os
from pathlib import Path

import pytest

from packages.domain import core_utils


def test_to_seattle_when_local_tz_missing(monkeypatch):
    ts = dt.datetime(2025, 1, 1, 12, 0, 0)

    class _FakeNow:
        tzinfo = None

        def astimezone(self):
            return self

    class _FakeDateTime:
        @staticmethod
        def now(_tz=None):
            return _FakeNow()

    monkeypatch.setattr(core_utils.dt, "datetime", _FakeDateTime)
    out = core_utils.to_seattle(ts)
    assert out.tzinfo is not None


def test_to_seattle_converts_aware_utc_to_pacific_and_keeps_instant():
    ts = dt.datetime(2025, 1, 1, 20, 0, 0, tzinfo=dt.timezone.utc)
    out = core_utils.to_seattle(ts)
    assert out.tzinfo is not None
    assert out.utcoffset() == dt.timedelta(hours=-8)
    assert out.hour == 12
    # Counterfactual: 若把 astimezone 改成 replace(tzinfo=...)，时间点会漂移。
    assert out.astimezone(dt.timezone.utc) == ts


def test_truncate_text_small_positive_limits_are_bounded():
    # Counterfactual: 若把边界判断改坏（如删除 max_chars<=3 分支），此处会失败。
    assert core_utils.truncate_text("abcdef", 1) == "."
    assert core_utils.truncate_text("abcdef", 2) == ".."
    assert len(core_utils.truncate_text("abcdef", 2)) == 2


def test_truncate_text_small_limit_keeps_short_text():
    # Regression: max_chars<=3 时，短文本应原样返回而非被 "." 覆盖。
    assert core_utils.truncate_text("a", 1) == "a"
    assert core_utils.truncate_text("ab", 2) == "ab"
    assert core_utils.truncate_text("abc", 3) == "abc"


def test_new_run_id_falls_back_when_datetime_now_fails(monkeypatch):
    class _BadDateTime:
        @staticmethod
        def now(_tz=None):
            raise RuntimeError("clock unavailable")

    monkeypatch.setattr(core_utils.dt, "datetime", _BadDateTime)
    rid = core_utils.new_run_id("job")
    assert rid.startswith("job_unknown_")
    assert len(rid.split("_")[-1]) == 8


def test_pid_alive_handles_all_error_modes(monkeypatch):
    monkeypatch.setattr(core_utils.os, "kill", lambda _pid, _sig: (_ for _ in ()).throw(ProcessLookupError()))
    assert core_utils._pid_alive(12345) is False

    monkeypatch.setattr(core_utils.os, "kill", lambda _pid, _sig: (_ for _ in ()).throw(PermissionError()))
    assert core_utils._pid_alive(12345) is True

    monkeypatch.setattr(core_utils.os, "kill", lambda _pid, _sig: None)
    assert core_utils._pid_alive(0) is False
    assert core_utils._pid_alive(12345) is True


def test_read_lock_metadata_handles_oserror_and_invalid_text(monkeypatch, tmp_path: Path):
    lock = tmp_path / "task.lock"
    lock.write_text("not-json", encoding="utf-8")
    assert core_utils._read_lock_metadata(lock) is None

    lock.write_text("", encoding="utf-8")
    assert core_utils._read_lock_metadata(lock) is None

    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("x")))
    assert core_utils._read_lock_metadata(lock) is None


def test_read_lock_metadata_supports_legacy_pid_payload(tmp_path: Path):
    # Counterfactual: 若删除 int(raw) 回退解析分支，此用例会变红。
    lock = tmp_path / "legacy.lock"
    lock.write_text("12345", encoding="utf-8")
    assert core_utils._read_lock_metadata(lock) == (12345, 0.0)


def test_acquire_file_lock_race_after_stale_cleanup(monkeypatch, tmp_path: Path):
    lock = tmp_path / "task.lock"
    lock.write_text("{}", encoding="utf-8")

    calls = {"count": 0}

    def fake_open(_path, _flags, _mode):
        calls["count"] += 1
        raise FileExistsError("race")

    monkeypatch.setattr(core_utils.os, "open", fake_open)
    monkeypatch.setattr(core_utils, "_read_lock_metadata", lambda _p: (999999, 1.0))
    monkeypatch.setattr(core_utils, "_pid_alive", lambda _pid: False)

    with pytest.raises(RuntimeError, match="lock file exists"):
        core_utils.acquire_file_lock(lock)
    assert calls["count"] == 2


def test_acquire_file_lock_with_invalid_metadata_and_non_stale_stat(tmp_path: Path):
    lock = tmp_path / "task.lock"
    lock.write_text("invalid-payload", encoding="utf-8")
    with pytest.raises(RuntimeError, match="lock file exists"):
        core_utils.acquire_file_lock(lock, stale_after_s=999999)


def test_acquire_file_lock_cleans_up_when_write_fails(monkeypatch, tmp_path: Path):
    lock = tmp_path / "task.lock"
    monkeypatch.setattr(core_utils.os, "write", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        core_utils.acquire_file_lock(lock)
    assert not lock.exists()


def test_release_file_lock_handles_stat_failure_and_fd_none(monkeypatch, tmp_path: Path):
    lock = tmp_path / "task.lock"
    fd = core_utils.acquire_file_lock(lock)
    real_stat = core_utils.os.stat
    monkeypatch.setattr(core_utils.os, "stat", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("x")))
    core_utils.release_file_lock(lock, fd)
    monkeypatch.setattr(core_utils.os, "stat", real_stat)
    assert lock.exists()

    core_utils.release_file_lock(lock, None)
    assert not lock.exists()


def test_acquire_file_lock_reclaims_stale_by_mtime_when_metadata_missing(tmp_path: Path):
    lock = tmp_path / "task.lock"
    lock.write_text("corrupted-metadata", encoding="utf-8")
    now = dt.datetime.now().timestamp()
    os.utime(lock, (now - 7200, now - 7200))

    fd = core_utils.acquire_file_lock(lock, stale_after_s=10)
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
        assert payload["pid"] == os.getpid()
        assert isinstance(payload["ts"], float)
    finally:
        core_utils.release_file_lock(lock, fd)


def test_release_file_lock_does_not_unlink_when_inode_mismatch(monkeypatch, tmp_path: Path):
    lock = tmp_path / "task.lock"
    fd = core_utils.acquire_file_lock(lock)

    replacement = tmp_path / "replacement.lock"
    replacement.write_text("new-owner", encoding="utf-8")
    replacement.replace(lock)

    class _Stat:
        def __init__(self, st_ino: int, st_dev: int):
            self.st_ino = st_ino
            self.st_dev = st_dev

    monkeypatch.setattr(core_utils.os, "fstat", lambda _fd: _Stat(1001, 77))
    monkeypatch.setattr(core_utils.os, "stat", lambda *_args, **_kwargs: _Stat(1002, 77))

    core_utils.release_file_lock(lock, fd)

    # Counterfactual: 若删除 same_inode 保护逻辑，这里会误删当前 lock 文件并失败。
    assert lock.exists()
    assert lock.read_text(encoding="utf-8") == "new-owner"
    lock.unlink()


def test_read_lock_metadata_parses_string_pid_and_ts(tmp_path: Path):
    lock = tmp_path / "task.lock"
    lock.write_text('{"pid":"42","ts":"1700000000.5"}', encoding="utf-8")
    pid, ts = core_utils._read_lock_metadata(lock) or (0, 0.0)
    assert pid == 42
    assert ts == 1700000000.5


def test_acquire_file_lock_treats_zero_ts_with_alive_pid_as_active(monkeypatch, tmp_path: Path):
    lock = tmp_path / "task.lock"
    lock.write_text(json.dumps({"pid": 12345, "ts": 0}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(core_utils, "_pid_alive", lambda _pid: True)

    with pytest.raises(RuntimeError, match="lock file exists"):
        core_utils.acquire_file_lock(lock, stale_after_s=1)
    assert lock.exists()


def test_release_file_lock_unlinks_when_same_inode(tmp_path: Path):
    lock = tmp_path / "task.lock"
    fd = core_utils.acquire_file_lock(lock)
    assert lock.exists()

    core_utils.release_file_lock(lock, fd)
    assert not lock.exists()


def test_sha1_file_chunk_boundary_and_empty_file(tmp_path: Path):
    payload = (b"abc123XYZ" * 131072) + b"tail"
    target = tmp_path / "payload.bin"
    target.write_bytes(payload)
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")

    digest_default = core_utils.sha1_file(target)
    digest_byte_chunk = core_utils.sha1_file(target, chunk_size=1)
    digest_odd_chunk = core_utils.sha1_file(target, chunk_size=77777)

    assert digest_default == digest_byte_chunk == digest_odd_chunk
    assert core_utils.sha1_file(empty) == "da39a3ee5e6b4b0d3255bfef95601890afd80709"
