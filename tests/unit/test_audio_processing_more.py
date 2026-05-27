from pathlib import Path

import pytest

from packages.infrastructure import audio_processing


@pytest.fixture(autouse=True)
def _stub_gemini_types(monkeypatch):
    class DummyPart:
        @staticmethod
        def from_bytes(*, data, mime_type):
            return {"data": data, "mime_type": mime_type}

    class DummyTypes:
        Part = DummyPart

    monkeypatch.setattr(audio_processing, "_lazy_import_gemini", lambda: (object(), DummyTypes))


def test_extract_transcript_payload_defaults():
    payload = {"transcript": " hello ", "language": " en ", "confidence": 0.5, "notes": " ok "}
    out = audio_processing.extract_transcript_payload(payload)
    assert out["transcript"] == "hello"
    assert out["transcript_lang"] == "en"
    assert out["transcript_confidence"] == 0.5


def test_prepare_audio_part_inline(tmp_path: Path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"dummy")

    part, mime, upload_name = audio_processing.prepare_audio_part(p, client=object(), inline_max_mb=10.0)
    assert part is not None
    assert mime.startswith("audio/")
    assert upload_name is None


def test_prepare_audio_part_upload(tmp_path: Path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"dummy")

    class DummyFile:
        name = "files/456"

    class DummyFiles:
        def upload(self, file: str):
            return DummyFile()

    class DummyClient:
        files = DummyFiles()

    part, mime, upload_name = audio_processing.prepare_audio_part(p, client=DummyClient(), inline_max_mb=0.0)
    assert part is not None
    assert upload_name == "files/456"


def test_prepare_audio_part_stat_error(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"dummy")
    real_stat = Path.stat

    def fake_stat(self):
        if self == p:
            raise OSError("no permission")
        return real_stat(self)

    monkeypatch.setattr(Path, "stat", fake_stat)

    with pytest.raises(RuntimeError):
        audio_processing.prepare_audio_part(p, client=object(), inline_max_mb=10.0)
