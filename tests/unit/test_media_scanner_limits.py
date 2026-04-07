from pathlib import Path

import pytest

from packages.infrastructure import media_scanner


def test_scan_media_stats_respects_max_files(tmp_path: Path):
    (tmp_path / "1.jpg").write_bytes(b"a")
    (tmp_path / "2.jpg").write_bytes(b"b")
    (tmp_path / "3.jpg").write_bytes(b"c")

    total_files, total_mb, exceeded = media_scanner.scan_media_stats(tmp_path, max_files=2)

    assert total_files == 3
    assert exceeded is True
    assert total_mb == 0.0


def test_scan_media_stats_respects_total_mb_limit(tmp_path: Path):
    (tmp_path / "a.jpg").write_bytes(b"x" * 2 * 1024 * 1024)

    total_files, total_mb, exceeded = media_scanner.scan_media_stats(tmp_path, max_total_mb=1.0)

    assert total_files == 1
    assert exceeded is True
    assert total_mb > 1.0


def test_scan_media_stats_ignores_stat_error(monkeypatch, tmp_path: Path):
    media = tmp_path / "a.jpg"
    media.write_bytes(b"x")

    real_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        # Path.is_symlink() probes via stat(follow_symlinks=False); only fail the size-read stat().
        if self == media and kwargs.get("follow_symlinks", True):
            raise OSError("stat failed")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)

    with pytest.warns(RuntimeWarning, match="Failed to read file size; treating it as 0 bytes"):
        total_files, total_mb, exceeded = media_scanner.scan_media_stats(tmp_path, max_total_mb=0.1)

    assert total_files == 1
    assert exceeded is False
    assert total_mb == 0.0


def test_guess_mime_audio_and_doc_allowlist():
    assert media_scanner.guess_mime(Path("voice.m4a")).startswith("audio/")
    assert media_scanner.guess_mime(Path("file.doc")).startswith("application/")


def test_detect_media_type_doc_and_ppt_variants():
    assert media_scanner.detect_media_type(Path("a.docx")) == "docx"
    assert media_scanner.detect_media_type(Path("a.doc")) == "doc"
    assert media_scanner.detect_media_type(Path("a.pptx")) == "pptx"
    assert media_scanner.detect_media_type(Path("a.ppt")) == "ppt"
    assert media_scanner.detect_media_type(Path("a.unknown")) == ""


def test_iter_media_files_walk_error_warns(monkeypatch, tmp_path: Path):
    def fake_walk(_root, onerror=None):
        if onerror is not None:
            onerror(OSError("permission denied"))
        return iter(())

    monkeypatch.setattr(media_scanner.os, "walk", fake_walk)
    with pytest.warns(RuntimeWarning, match="Directory traversal failed and was skipped"):
        out = list(media_scanner.iter_media_files(tmp_path))
    assert out == []
