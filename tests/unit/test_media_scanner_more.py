from pathlib import Path

from packages.infrastructure import media_scanner


def test_guess_mime_allowlist():
    assert media_scanner.guess_mime(Path("a.png")) == "image/png"


def test_guess_mime_fallback(monkeypatch):
    monkeypatch.setattr(media_scanner.mimetypes, "guess_type", lambda _: (None, None))
    assert media_scanner.guess_mime(Path("a.unknown")) == "application/octet-stream"
