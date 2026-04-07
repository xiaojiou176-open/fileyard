from pathlib import Path

from packages.infrastructure import gemini_client


def test_build_file_part_inline(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"hello")

    class DummyPart:
        @staticmethod
        def from_bytes(data, mime_type):
            return (data, mime_type)

    class DummyTypes:
        Part = DummyPart

        class GenerateContentConfig:
            def __init__(self, temperature=0.0, response_mime_type=None):
                pass

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", lambda: (None, DummyTypes))
    monkeypatch.setattr(gemini_client, "guess_mime", lambda path: "text/plain")

    part, mime, upload_name = gemini_client.build_file_part(p, client=object(), inline_max_mb=10.0)
    assert mime == "text/plain"
    assert upload_name is None
    assert part[1] == "text/plain"


def test_build_file_part_upload(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"hello")

    class DummyFile:
        name = "files/999"

    class DummyFiles:
        def upload(self, file: str):
            return DummyFile()

    class DummyClient:
        files = DummyFiles()

    class DummyTypes:
        class GenerateContentConfig:
            def __init__(self, temperature=0.0, response_mime_type=None):
                pass

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", lambda: (None, DummyTypes))
    monkeypatch.setattr(gemini_client, "guess_mime", lambda path: "text/plain")

    part, mime, upload_name = gemini_client.build_file_part(p, client=DummyClient(), inline_max_mb=0.0)
    assert mime == "text/plain"
    assert upload_name == "files/999"
    assert part.name == "files/999"
