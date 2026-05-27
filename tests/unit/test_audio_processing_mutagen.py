import sys
import types
from pathlib import Path
from typing import Any

from packages.infrastructure import audio_processing


def test_extract_audio_fields_with_mutagen(monkeypatch, tmp_path: Path):
    class DummyInfo:
        length = 12.3
        sample_rate = 44100
        channels = 2
        bitrate = 128000

    class DummyAudio:
        info = DummyInfo()

    def fake_file(path: str):
        return DummyAudio()

    module: Any = types.ModuleType("mutagen")
    setattr(module, "File", fake_file)
    monkeypatch.setitem(sys.modules, "mutagen", module)

    p = tmp_path / "a.mp3"
    p.write_bytes(b"data")

    out = audio_processing.extract_audio_fields(p)
    assert out["duration_s"] == 12.3
    assert out["sample_rate"] == 44100
    assert out["channels"] == 2
    assert out["bitrate_kbps"] == 128
