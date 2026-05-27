import builtins
import subprocess
import sys
import types
from pathlib import Path

import pytest

from packages.infrastructure import audio_processing


def test_trusted_exec_and_ffmpeg_resolution(monkeypatch, tmp_path: Path):
    fake_bin = tmp_path / "ffmpeg"
    fake_bin.write_text("x", encoding="utf-8")

    monkeypatch.setattr(audio_processing, "_is_test_hooks_enabled", lambda: False)
    assert audio_processing._is_trusted_executable(fake_bin) is False

    monkeypatch.setattr(audio_processing.shutil, "which", lambda _name: None)
    assert audio_processing._resolve_ffmpeg_path() is None


def test_normalize_timeout_and_plan_segments_edges():
    assert audio_processing._normalize_timeout("bad") == 120.0
    assert audio_processing._normalize_timeout(0) == 120.0
    assert audio_processing.plan_audio_segments(10.0, 0.0, 1) == []
    assert audio_processing.plan_audio_segments(8.0, 10.0, 3) == [(0.0, 8.0)]
    assert audio_processing.plan_audio_segments(20.0, 4.0, 1) == [(8.0, 4.0)]


def test_extract_audio_fields_import_and_missing_info(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.mp3"
    p.write_bytes(b"x")

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mutagen":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sys.modules.pop("mutagen", None)
    out = audio_processing.extract_audio_fields(p)
    assert out == {"duration_s": "", "sample_rate": "", "channels": "", "bitrate_kbps": ""}

    module = types.ModuleType("mutagen")
    setattr(module, "File", lambda _path: object())
    monkeypatch.setitem(sys.modules, "mutagen", module)
    monkeypatch.setattr(builtins, "__import__", real_import)
    out2 = audio_processing.extract_audio_fields(p)
    assert out2 == {"duration_s": "", "sample_rate": "", "channels": "", "bitrate_kbps": ""}


def test_extract_audio_segments_cleans_failed_output(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"dummy")
    monkeypatch.setattr(audio_processing, "_resolve_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    def fake_run(cmd, **_kwargs):
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"temp")
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr(audio_processing.subprocess, "run", fake_run)
    outputs, temp_dir = audio_processing.extract_audio_segments(p, [(0.0, 1.0)])
    assert outputs == []
    assert temp_dir is not None
    assert list(temp_dir.glob("*.wav")) == []


def test_prepare_audio_part_error_and_upload_fallback_branch(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"dummy")

    class DummyPart:
        @staticmethod
        def from_bytes(*, data, mime_type):
            return {"size": len(data), "mime": mime_type}

    class DummyTypes:
        Part = DummyPart

    monkeypatch.setattr(audio_processing, "_lazy_import_gemini", lambda: (object(), DummyTypes))

    real_read_bytes = Path.read_bytes

    def bad_read(self):
        if self == p:
            raise OSError("cannot read")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", bad_read)
    with pytest.raises(RuntimeError, match="Failed to read audio file bytes"):
        audio_processing.prepare_audio_part(p, client=object(), inline_max_mb=10.0)

    monkeypatch.setattr(Path, "read_bytes", real_read_bytes)

    class DummyFileRef:
        name = "files/xyz"

    class DummyFiles:
        def upload(self, file: str):
            assert file.endswith("a.wav")
            return DummyFileRef()

    class DummyClient:
        files = DummyFiles()

    monkeypatch.setattr(
        "packages.infrastructure.gemini_client._run_with_timeout",
        lambda fn, _timeout: fn(),
        raising=True,
    )
    part, mime, upload_name = audio_processing.prepare_audio_part(
        p,
        client=DummyClient(),
        inline_max_mb=0.0,
        timeout_s=None,
    )
    assert part.name == "files/xyz"
    assert mime.startswith("audio/")
    assert upload_name == "files/xyz"


def test_merge_transcript_segments_invalid_confidence_and_empty_fields():
    transcript, lang, conf = audio_processing.merge_transcript_segments(
        [
            {"text": "", "language": "", "confidence": "bad"},
            {"text": "hello", "language": "en", "confidence": 0.8},
            {"text": "world", "language": "fr", "confidence": 0.4},
        ]
    )
    assert transcript == "hello\nworld"
    assert lang == "en"
    assert conf == 0.6
