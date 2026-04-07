import datetime as dt
import json
import os
import time
from pathlib import Path

from packages.domain import core_utils


def test_truncate_text_zero():
    assert core_utils.truncate_text("abc", 0) == ""


def test_to_seattle_zoneinfo_failure(monkeypatch):
    class DummyZoneInfo:
        def __init__(self, name):
            raise Exception("no tz")

    monkeypatch.setattr(core_utils, "ZoneInfo", DummyZoneInfo)
    ts = dt.datetime(2025, 1, 1, 12, 0, 0)
    out = core_utils.to_seattle(ts)
    assert out == ts


def test_acquire_file_lock_recovers_stale_lock(tmp_path: Path):
    lock = tmp_path / "task.lock"
    lock.write_text(json.dumps({"pid": 999999, "ts": time.time() - 4000}, ensure_ascii=False), encoding="utf-8")
    fd = core_utils.acquire_file_lock(lock, stale_after_s=10)
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
        assert payload["pid"] == os.getpid()
    finally:
        core_utils.release_file_lock(lock, fd)


def test_acquire_file_lock_blocks_active_lock(tmp_path: Path):
    lock = tmp_path / "task.lock"
    lock.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}, ensure_ascii=False), encoding="utf-8")
    try:
        try:
            core_utils.acquire_file_lock(lock, stale_after_s=3600)
            raised = False
        except RuntimeError:
            raised = True
        assert raised is True
    finally:
        lock.unlink(missing_ok=True)
