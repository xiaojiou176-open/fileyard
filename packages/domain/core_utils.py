# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from contextlib import suppress
from pathlib import Path
from zoneinfo import ZoneInfo


def sha1_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    # Shared manifest/report dedup fingerprint helper; not for cryptographic use.
    hasher = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def safe_stat_mtime(path: Path) -> dt.datetime:
    ts = path.stat().st_mtime
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return "." * max_chars
    return text[: max_chars - 3] + "..."


def to_seattle(ts: dt.datetime) -> dt.datetime:
    try:
        seattle = ZoneInfo("America/Los_Angeles")
    except Exception:
        return ts

    if ts.tzinfo is None:
        local_tz = dt.datetime.now().astimezone().tzinfo
        if local_tz is None:
            return ts.replace(tzinfo=seattle)
        ts = ts.replace(tzinfo=local_tz)
    return ts.astimezone(seattle)


def new_run_id(prefix: str = "run") -> str:
    try:
        now = dt.datetime.now(dt.timezone.utc)
        stamp = f"{now.year:04d}{now.month:02d}{now.day:02d}_{now.hour:02d}{now.minute:02d}{now.second:02d}"
    except Exception:
        stamp = "unknown"
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def _read_lock_metadata(lock_path: Path) -> tuple[int, float] | None:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        pid = int(payload.get("pid", 0))
        ts = float(payload.get("ts", 0.0))
        return pid, ts
    except Exception:
        try:
            return int(raw), 0.0
        except Exception:
            return None


def acquire_file_lock(lock_path: Path, stale_after_s: int = 1800) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags, 0o644)
    except FileExistsError as exc:
        metadata = _read_lock_metadata(lock_path)
        now = dt.datetime.now(dt.timezone.utc).timestamp()
        if metadata is not None:
            pid, ts = metadata
            stale = (ts > 0 and now - ts > stale_after_s) or not _pid_alive(pid)
            if stale:
                with suppress(OSError):
                    lock_path.unlink()
                try:
                    fd = os.open(str(lock_path), flags, 0o644)
                except FileExistsError as race_exc:
                    raise RuntimeError(f"Another Fileyard task is already running; lock file exists: {lock_path}") from race_exc
            else:
                raise RuntimeError(f"Another Fileyard task is already running; lock file exists: {lock_path}") from exc
        else:
            stale = False
            try:
                stat = lock_path.stat()
                stale = now - float(stat.st_mtime) > stale_after_s
            except OSError:
                stale = True
            if stale:
                with suppress(OSError):
                    lock_path.unlink()
                try:
                    fd = os.open(str(lock_path), flags, 0o644)
                except FileExistsError as race_exc:
                    raise RuntimeError(f"Another Fileyard task is already running; lock file exists: {lock_path}") from race_exc
            else:
                raise RuntimeError(f"Another Fileyard task is already running; lock file exists: {lock_path}") from exc
    payload = {
        "pid": os.getpid(),
        "ts": dt.datetime.now(dt.timezone.utc).timestamp(),
    }
    try:
        os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        os.fsync(fd)
    except Exception:
        with suppress(OSError):
            os.close(fd)
        with suppress(OSError):
            lock_path.unlink()
        raise
    return fd


def release_file_lock(lock_path: Path, fd: int | None) -> None:
    if fd is not None:
        same_inode = False
        try:
            fd_stat = os.fstat(fd)
            path_stat = os.stat(lock_path, follow_symlinks=False)
            same_inode = fd_stat.st_ino == path_stat.st_ino and fd_stat.st_dev == path_stat.st_dev
        except OSError:
            same_inode = False
        if same_inode:
            with suppress(OSError):
                lock_path.unlink()
        with suppress(OSError):
            os.close(fd)
        return
    with suppress(OSError):
        lock_path.unlink()
