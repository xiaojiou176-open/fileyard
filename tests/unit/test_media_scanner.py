import os
from pathlib import Path

from packages.infrastructure import media_scanner


def test_detect_media_type():
    assert media_scanner.detect_media_type(Path("a.jpg")) == "image"
    assert media_scanner.detect_media_type(Path("a.mp3")) == "audio"
    assert media_scanner.detect_media_type(Path("a.pdf")) == "pdf"


def test_iter_media_files(tmp_path: Path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.mp3").write_bytes(b"x")
    (tmp_path / "c.txt").write_text("nope", encoding="utf-8")
    files = list(media_scanner.iter_media_files(tmp_path))
    names = {p.name for p in files}
    assert names == {"a.jpg", "b.mp3"}
    assert media_scanner.count_media_files(tmp_path) == 2


def test_iter_media_files_skips_symlink(tmp_path: Path):
    target = tmp_path / "target.jpg"
    target.write_bytes(b"x")
    link = tmp_path / "link.jpg"
    os.symlink(target, link)

    files = list(media_scanner.iter_media_files(tmp_path))
    names = {p.name for p in files}
    assert "link.jpg" not in names
    assert "target.jpg" in names
