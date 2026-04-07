from pathlib import Path

from packages.infrastructure import audio_processing


def test_extract_audio_segments_success(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(audio_processing, "_resolve_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    p = tmp_path / "a.wav"
    p.write_bytes(b"dummy")

    def fake_run(cmd, stdout=None, stderr=None, check=None, **kwargs):
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"seg")
        return None

    monkeypatch.setattr(audio_processing.subprocess, "run", fake_run)

    segments = [(0.0, 1.0), (1.0, 1.0)]
    outputs, temp_dir = audio_processing.extract_audio_segments(p, segments)
    assert len(outputs) == 2
    assert temp_dir is not None
    for out_path, _, _ in outputs:
        assert out_path.exists()


def test_extract_audio_segments_partial_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(audio_processing, "_resolve_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    p = tmp_path / "a.wav"
    p.write_bytes(b"dummy")

    def fake_run(cmd, stdout=None, stderr=None, check=None, **kwargs):
        out_path = Path(cmd[-1])
        if "seg_1" in out_path.name:
            out_path.write_bytes(b"seg")
            return None
        raise RuntimeError("ffmpeg error")

    monkeypatch.setattr(audio_processing.subprocess, "run", fake_run)

    segments = [(0.0, 1.0), (1.0, 1.0)]
    outputs, temp_dir = audio_processing.extract_audio_segments(p, segments)
    assert len(outputs) == 1
    assert temp_dir is not None


def test_extract_audio_segments_timeout_has_lower_bound(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(audio_processing, "_resolve_ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    p = tmp_path / "a.wav"
    p.write_bytes(b"dummy")
    captured = {}

    def fake_run(cmd, stdout=None, stderr=None, check=None, timeout=None, **kwargs):
        captured["timeout"] = timeout
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"seg")
        return None

    monkeypatch.setattr(audio_processing.subprocess, "run", fake_run)
    outputs, temp_dir = audio_processing.extract_audio_segments(p, [(0.0, 1.0)], timeout_s=0.0)
    assert len(outputs) == 1
    assert temp_dir is not None
    assert captured["timeout"] == 120.0
