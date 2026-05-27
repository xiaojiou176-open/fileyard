from pathlib import Path

from packages.infrastructure import audio_processing


def test_extract_audio_segments_no_ffmpeg(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(audio_processing, "_resolve_ffmpeg_path", lambda: None)
    p = tmp_path / "a.wav"
    p.write_bytes(b"dummy")
    segments = audio_processing.plan_audio_segments(120.0, 10.0, 3)
    outputs, temp_dir = audio_processing.extract_audio_segments(p, segments)
    assert outputs == []
    assert temp_dir is None


def test_plan_audio_segments_many():
    segs = audio_processing.plan_audio_segments(100.0, 5.0, 5)
    assert len(segs) == 5
    assert segs[0][0] == 0.0


def test_resolve_ffmpeg_path_rejects_untrusted(monkeypatch):
    monkeypatch.setattr(audio_processing.shutil, "which", lambda _name: "/tmp/ffmpeg")
    monkeypatch.setattr(audio_processing, "_is_trusted_executable", lambda _p: False)
    assert audio_processing._resolve_ffmpeg_path() is None
