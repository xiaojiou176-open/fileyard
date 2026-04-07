import builtins
import sys
import types
from pathlib import Path

from packages.infrastructure import audio_processing


def test_is_test_hooks_enabled_reads_env(monkeypatch):
    monkeypatch.delenv("MOVI_ENABLE_TEST_HOOKS", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert audio_processing._is_test_hooks_enabled() is False

    monkeypatch.setenv("MOVI_ENABLE_TEST_HOOKS", "1")
    assert audio_processing._is_test_hooks_enabled() is True

    monkeypatch.setenv("MOVI_ENABLE_TEST_HOOKS", "0")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests::case")
    assert audio_processing._is_test_hooks_enabled() is True


def test_trusted_exec_test_mode_and_resolve_ffmpeg(monkeypatch, tmp_path: Path):
    fake_dir = tmp_path / "bin-dir"
    fake_dir.mkdir()
    monkeypatch.setattr(audio_processing, "_is_test_hooks_enabled", lambda: True)
    assert audio_processing._is_trusted_executable(fake_dir) is False

    fake_bin = tmp_path / "ffmpeg"
    fake_bin.write_text("bin", encoding="utf-8")
    monkeypatch.setattr(audio_processing.shutil, "which", lambda _name: str(fake_bin))
    monkeypatch.setattr(audio_processing, "_is_trusted_executable", lambda _path: True)
    assert audio_processing._resolve_ffmpeg_path() == str(fake_bin.resolve())

    monkeypatch.setattr(audio_processing, "_resolve_ffmpeg_path", lambda: str(fake_bin))
    assert audio_processing.has_ffmpeg() is True
    monkeypatch.setattr(audio_processing, "_resolve_ffmpeg_path", lambda: None)
    assert audio_processing.has_ffmpeg() is False


def test_extract_audio_fields_cast_error_and_partial_fields(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.mp3"
    p.write_bytes(b"x")

    class _InfoBad:
        length = 1.25
        sample_rate = "oops"
        channels = 2
        bitrate = 64000

    class _AudioBad:
        info = _InfoBad()

    module_bad = types.ModuleType("mutagen")
    setattr(module_bad, "File", lambda _path: _AudioBad())
    monkeypatch.setitem(sys.modules, "mutagen", module_bad)
    out_bad = audio_processing.extract_audio_fields(p)
    assert out_bad["duration_s"] == 1.25
    assert out_bad["sample_rate"] == ""

    class _InfoPartial:
        length = 2.0
        sample_rate = None
        channels = None
        bitrate = None

    class _AudioPartial:
        info = _InfoPartial()

    module_partial = types.ModuleType("mutagen")
    setattr(module_partial, "File", lambda _path: _AudioPartial())
    monkeypatch.setitem(sys.modules, "mutagen", module_partial)
    out_partial = audio_processing.extract_audio_fields(p)
    assert out_partial["duration_s"] == 2.0
    assert out_partial["sample_rate"] == ""
    assert out_partial["channels"] == ""
    assert out_partial["bitrate_kbps"] == ""


def test_extract_audio_segments_empty_and_no_segments(tmp_path: Path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"audio")
    outputs, temp_dir = audio_processing.extract_audio_segments(p, [])
    assert outputs == []
    assert temp_dir is None


def test_extract_audio_fields_import_error_path(monkeypatch, tmp_path: Path):
    p = tmp_path / "b.mp3"
    p.write_bytes(b"audio")

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "mutagen":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    sys.modules.pop("mutagen", None)
    out = audio_processing.extract_audio_fields(p)
    assert out == {"duration_s": "", "sample_rate": "", "channels": "", "bitrate_kbps": ""}
