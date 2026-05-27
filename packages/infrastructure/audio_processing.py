# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import subprocess  # nosec B404
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from packages.domain.pipeline_config import (
    KEY_BITRATE_KBPS,
    KEY_CHANNELS,
    KEY_DURATION_S,
    KEY_SAMPLE_RATE,
    KEY_TRANSCRIPT,
    KEY_TRANSCRIPT_CONF,
    KEY_TRANSCRIPT_LANG,
)
from packages.infrastructure.gemini_client import _lazy_import_gemini
from packages.infrastructure.media_scanner import guess_mime

_MIN_SUBPROCESS_TIMEOUT_S = 1.0
_DEFAULT_SUBPROCESS_TIMEOUT_S = 120.0
_TRUSTED_BIN_DIRS = (
    "/usr/bin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/opt/local/bin",
)


def _is_test_hooks_enabled() -> bool:
    import os

    return os.environ.get("FILEYARD_ENABLE_TEST_HOOKS", "") == "1" or bool(os.environ.get("PYTEST_CURRENT_TEST", ""))


def _is_trusted_executable(path: Path) -> bool:
    if _is_test_hooks_enabled():
        return path.exists() and path.is_file()
    if not path.exists() or not path.is_file() or not path.is_absolute():
        return False
    resolved = path.resolve()
    text = str(resolved)
    return any(text == base or text.startswith(base + "/") for base in _TRUSTED_BIN_DIRS)


def _resolve_ffmpeg_path() -> str | None:
    raw = shutil.which("ffmpeg")
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not _is_trusted_executable(candidate):
        return None
    return str(candidate.resolve())


def _normalize_timeout(timeout_s: float, *, default_s: float = _DEFAULT_SUBPROCESS_TIMEOUT_S) -> float:
    try:
        parsed = float(timeout_s)
    except (TypeError, ValueError):
        parsed = default_s
    if parsed <= 0:
        parsed = default_s
    return max(_MIN_SUBPROCESS_TIMEOUT_S, parsed)


def extract_audio_fields(path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        KEY_DURATION_S: "",
        KEY_SAMPLE_RATE: "",
        KEY_CHANNELS: "",
        KEY_BITRATE_KBPS: "",
    }
    try:
        from mutagen import File as MutagenFile  # type: ignore
    except (ImportError, RuntimeError):
        return out

    try:
        audio = MutagenFile(str(path))
        if not audio or not hasattr(audio, "info") or audio.info is None:
            return out
        info = audio.info
        duration = getattr(info, "length", None)
        sample_rate = getattr(info, "sample_rate", None)
        channels = getattr(info, "channels", None)
        bitrate = getattr(info, "bitrate", None)

        if duration is not None:
            out[KEY_DURATION_S] = round(float(duration), 3)
        if sample_rate is not None:
            out[KEY_SAMPLE_RATE] = int(sample_rate)
        if channels is not None:
            out[KEY_CHANNELS] = int(channels)
        if bitrate is not None:
            out[KEY_BITRATE_KBPS] = int(bitrate / 1000)
    except (AttributeError, OSError, TypeError, ValueError):
        return out

    return out


def has_ffmpeg() -> bool:
    return _resolve_ffmpeg_path() is not None


def plan_audio_segments(
    duration_s: float,
    segment_seconds: float,
    segment_count: int,
) -> List[Tuple[float, float]]:
    if segment_seconds <= 0 or segment_count <= 0:
        return []
    if duration_s <= segment_seconds:
        return [(0.0, duration_s)]
    if segment_count == 1:
        mid = max(0.0, (duration_s - segment_seconds) / 2.0)
        return [(mid, segment_seconds)]
    segments: List[Tuple[float, float]] = []
    segments.append((0.0, min(segment_seconds, duration_s)))
    if segment_count >= 2:
        mid = max(0.0, (duration_s - segment_seconds) / 2.0)
        segments.append((mid, segment_seconds))
    if segment_count >= 3:
        end_start = max(0.0, duration_s - segment_seconds)
        segments.append((end_start, segment_seconds))
    if segment_count > 3:
        step = max(segment_seconds, duration_s / float(segment_count))
        segments = []
        for i in range(segment_count):
            start = min(max(0.0, i * step), max(0.0, duration_s - segment_seconds))
            segments.append((start, segment_seconds))
    return segments


def extract_audio_segments(
    path: Path,
    segments: List[Tuple[float, float]],
    timeout_s: float = 120.0,
) -> Tuple[List[Tuple[Path, float, float]], Optional[Path]]:
    if not segments:
        return [], None
    ffmpeg_bin = _resolve_ffmpeg_path()
    if ffmpeg_bin is None:
        return [], None
    temp_dir = Path(tempfile.mkdtemp(prefix="audio_segments_"))
    outputs: List[Tuple[Path, float, float]] = []
    safe_timeout_s = _normalize_timeout(timeout_s)
    for idx, (start_s, length_s) in enumerate(segments, 1):
        out_path = temp_dir / f"seg_{idx}.wav"
        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss",
            str(start_s),
            "-t",
            str(length_s),
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(out_path),
        ]
        try:
            subprocess.run(  # nosec B603
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=safe_timeout_s,
            )
            outputs.append((out_path, start_s, length_s))
        except (subprocess.CalledProcessError, OSError, RuntimeError, subprocess.TimeoutExpired):
            if out_path.exists():
                with suppress(OSError):
                    out_path.unlink()
    return outputs, temp_dir


def prepare_audio_part(
    path: Path,
    client,
    inline_max_mb: float,
    *,
    timeout_s: float | None = 60.0,
) -> Tuple[Any, str, Optional[str]]:
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
    except OSError as exc:
        raise RuntimeError(f"Failed to read audio file metadata: {path}") from exc
    _, types = _lazy_import_gemini()
    mime = guess_mime(path)

    if size_mb <= inline_max_mb:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"Failed to read audio file bytes: {path}") from exc
        audio_part = types.Part.from_bytes(data=data, mime_type=mime)
        return audio_part, mime, None

    if timeout_s is not None and timeout_s > 0:
        from packages.infrastructure.gemini_client import _run_with_timeout

        safe_timeout_s = _normalize_timeout(timeout_s, default_s=60.0)
        file_ref = _run_with_timeout(lambda: client.files.upload(file=str(path)), safe_timeout_s)
    else:
        safe_timeout_s = _normalize_timeout(60.0, default_s=60.0)
        from packages.infrastructure.gemini_client import _run_with_timeout

        file_ref = _run_with_timeout(lambda: client.files.upload(file=str(path)), safe_timeout_s)
    upload_name = getattr(file_ref, "name", None)
    return file_ref, mime, upload_name


def extract_transcript_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    transcript = str(payload.get("transcript", "") or "").strip()
    language = str(payload.get("language", "") or "").strip()
    confidence = payload.get("confidence", "")
    notes = str(payload.get("notes", "") or "").strip()
    return {
        KEY_TRANSCRIPT: transcript,
        KEY_TRANSCRIPT_LANG: language,
        KEY_TRANSCRIPT_CONF: confidence,
        "transcript_notes": notes,
    }


def merge_transcript_segments(
    segments: List[Dict[str, Any]],
) -> Tuple[str, str, float]:
    texts: List[str] = []
    langs: List[str] = []
    confs: List[float] = []
    for seg in segments:
        text = seg.get("text", "")
        lang = seg.get("language", "")
        conf = seg.get("confidence", "")
        if text:
            texts.append(text)
        if lang:
            langs.append(lang)
        try:
            conf_val = float(conf)
        except (TypeError, ValueError):
            conf_val = None
        if conf_val is not None:
            confs.append(conf_val)

    transcript = "\n".join([t for t in texts if t]).strip()
    lang = langs[0] if langs else ""
    conf = round(sum(confs) / float(len(confs)), 3) if confs else 0.0
    return transcript, lang, conf
