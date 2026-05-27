import io
from pathlib import Path

import pytest

from packages.infrastructure import document_conversion


def test_is_trusted_executable_strict_mode(monkeypatch, tmp_path: Path):
    fake_bin = tmp_path / "tool"
    fake_bin.write_text("x", encoding="utf-8")
    monkeypatch.setattr(document_conversion, "_is_test_hooks_enabled", lambda: False)
    assert document_conversion._is_trusted_executable(fake_bin) is False
    assert document_conversion._is_trusted_executable(Path("relative/tool")) is False


def test_normalize_timeout_and_tail_stderr_paths():
    assert document_conversion._normalize_timeout("bad") == 120.0
    assert document_conversion._normalize_timeout(-1) == 120.0
    assert document_conversion._normalize_timeout(0.1) == 1.0

    class _BadFile:
        def seek(self, *_args):
            raise OSError("seek failed")

    assert document_conversion._tail_stderr_from_file(_BadFile()) == ""
    assert document_conversion._tail_stderr_from_file(io.BytesIO(b"   ")) == ""


def test_validate_source_file_error_paths(monkeypatch, tmp_path: Path):
    with pytest.raises(RuntimeError, match="missing or not a regular file"):
        document_conversion._validate_source_file(tmp_path / "missing.docx")

    src = tmp_path / "a.docx"
    src.write_bytes(b"x")
    monkeypatch.setattr(Path, "exists", lambda self: self == src)
    monkeypatch.setattr(Path, "is_file", lambda self: self == src)
    monkeypatch.setattr(Path, "stat", lambda self: (_ for _ in ()).throw(OSError("no stat")))
    with pytest.raises(RuntimeError, match="Failed to read document file metadata"):
        document_conversion._validate_source_file(src)


def test_find_libreoffice_and_unoconv_additional_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(document_conversion.shutil, "which", lambda _name: None)
    monkeypatch.setattr(document_conversion, "_is_trusted_executable", lambda _p: False)
    assert document_conversion.find_libreoffice() is None
    assert document_conversion.find_unoconv() is None

    fake_unoconv = tmp_path / "unoconv"
    fake_unoconv.write_text("x", encoding="utf-8")
    monkeypatch.setattr(document_conversion.shutil, "which", lambda _name: str(fake_unoconv))
    monkeypatch.setattr(document_conversion, "_is_trusted_executable", lambda _p: True)
    assert document_conversion.find_unoconv() == str(fake_unoconv.resolve())


def test_convert_to_pdf_unoconv_failure_and_missing_output(monkeypatch, tmp_path: Path):
    src = tmp_path / "a.docx"
    src.write_bytes(b"docx")
    fake_unoconv = tmp_path / "unoconv"
    fake_unoconv.write_text("x", encoding="utf-8")

    out_root = tmp_path / "out"
    out_root.mkdir()

    def fake_mkdtemp(prefix: str):
        target = out_root / prefix.strip("_")
        target.mkdir(exist_ok=True)
        return str(target)

    monkeypatch.setattr(document_conversion, "find_libreoffice", lambda: None)
    monkeypatch.setattr(document_conversion, "find_unoconv", lambda: str(fake_unoconv))
    monkeypatch.setattr(document_conversion.tempfile, "mkdtemp", fake_mkdtemp)

    def fake_run_fail(*_args, **_kwargs):
        raise RuntimeError("convert failed")

    monkeypatch.setattr(document_conversion.subprocess, "run", fake_run_fail)
    with pytest.raises(RuntimeError, match="unoconv PDF conversion failed"):
        document_conversion.convert_to_pdf(src)

    def fake_run_ok(*_args, **_kwargs):
        return None

    monkeypatch.setattr(document_conversion.subprocess, "run", fake_run_ok)
    with pytest.raises(RuntimeError, match="did not produce a PDF file"):
        document_conversion.convert_to_pdf(src)
