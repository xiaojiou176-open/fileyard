from pathlib import Path

import pytest

from packages.infrastructure import document_conversion


def test_convert_to_pdf_libreoffice_run_failure(monkeypatch, tmp_path: Path):
    fake_soffice = tmp_path / "soffice"
    fake_soffice.write_text("x", encoding="utf-8")

    def fake_mkdtemp(prefix: str):
        out = tmp_path / "tmp"
        out.mkdir(exist_ok=True)
        return str(out)

    def fake_run(cmd, stdout=None, stderr=None, check=None, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(document_conversion, "find_libreoffice", lambda: str(fake_soffice))
    monkeypatch.setattr(document_conversion.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(document_conversion.subprocess, "run", fake_run)

    src = tmp_path / "a.docx"
    src.write_bytes(b"docx")

    with pytest.raises(RuntimeError):
        document_conversion.convert_to_pdf(src)


def test_convert_to_pdf_libreoffice_no_pdf(monkeypatch, tmp_path: Path):
    fake_soffice = tmp_path / "soffice"
    fake_soffice.write_text("x", encoding="utf-8")

    def fake_mkdtemp(prefix: str):
        out = tmp_path / "tmp2"
        out.mkdir(exist_ok=True)
        return str(out)

    def fake_run(cmd, stdout=None, stderr=None, check=None, **kwargs):
        return None

    monkeypatch.setattr(document_conversion, "find_libreoffice", lambda: str(fake_soffice))
    monkeypatch.setattr(document_conversion.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(document_conversion.subprocess, "run", fake_run)

    src = tmp_path / "a.docx"
    src.write_bytes(b"docx")

    with pytest.raises(RuntimeError):
        document_conversion.convert_to_pdf(src)


def test_convert_to_pdf_timeout_has_lower_bound(monkeypatch, tmp_path: Path):
    fake_soffice = tmp_path / "soffice"
    fake_soffice.write_text("x", encoding="utf-8")

    def fake_run(cmd, stdout=None, stderr=None, check=None, timeout=None, **kwargs):
        assert timeout == 120.0
        out_dir = Path(cmd[cmd.index("--outdir") + 1])
        (out_dir / "a.pdf").write_bytes(b"pdf")
        return None

    monkeypatch.setattr(document_conversion, "find_libreoffice", lambda: str(fake_soffice))
    monkeypatch.setattr(document_conversion.subprocess, "run", fake_run)

    src = tmp_path / "a.docx"
    src.write_bytes(b"docx")
    pdf_path, temp_dir, tool = document_conversion.convert_to_pdf(src, timeout_s=0.0)
    assert pdf_path.exists()
    assert temp_dir is not None
    assert tool == "libreoffice"


def test_convert_to_pdf_rejects_empty_file(monkeypatch, tmp_path: Path):
    src = tmp_path / "empty.docx"
    src.write_bytes(b"")

    monkeypatch.setattr(document_conversion, "find_libreoffice", lambda: None)
    monkeypatch.setattr(document_conversion, "find_unoconv", lambda: None)

    with pytest.raises(RuntimeError, match="empty and cannot be converted"):
        document_conversion.convert_to_pdf(src)


def test_convert_to_pdf_rejects_unreadable_file(monkeypatch, tmp_path: Path):
    src = tmp_path / "a.docx"
    src.write_bytes(b"docx")

    monkeypatch.setattr(document_conversion.os, "access", lambda *_args, **_kwargs: False)
    with pytest.raises(RuntimeError, match="not readable"):
        document_conversion.convert_to_pdf(src)
