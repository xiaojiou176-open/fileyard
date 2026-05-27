from pathlib import Path

from packages.infrastructure import document_conversion


def test_find_libreoffice_prefers_existing(monkeypatch, tmp_path: Path):
    fake = tmp_path / "soffice"
    fake.write_text("x", encoding="utf-8")

    def fake_which(name: str):
        if name in {"soffice", "libreoffice"}:
            return str(fake)
        return None

    monkeypatch.setattr(document_conversion.shutil, "which", fake_which)

    assert document_conversion.find_libreoffice() == str(fake)


def test_convert_to_pdf_with_fake_soffice(monkeypatch, tmp_path: Path):
    fake_soffice = tmp_path / "soffice"
    fake_soffice.write_text("x", encoding="utf-8")

    work = tmp_path / "work"
    work.mkdir()

    def fake_mkdtemp(prefix: str):
        out = work / "tmp"
        out.mkdir(exist_ok=True)
        return str(out)

    def fake_run(cmd, stdout=None, stderr=None, check=None, **kwargs):
        # Create a fake PDF in the temp dir
        out_dir = Path(cmd[cmd.index("--outdir") + 1])
        pdf_path = out_dir / "input.pdf"
        pdf_path.write_bytes(b"pdf")

    monkeypatch.setattr(document_conversion, "find_libreoffice", lambda: str(fake_soffice))
    monkeypatch.setattr(document_conversion.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(document_conversion.subprocess, "run", fake_run)

    src = tmp_path / "input.docx"
    src.write_bytes(b"docx")

    pdf_path, temp_dir, tool = document_conversion.convert_to_pdf(src)
    assert pdf_path.exists()
    assert tool == "libreoffice"
    assert temp_dir is not None


def test_convert_to_pdf_with_unoconv(monkeypatch, tmp_path: Path):
    fake_unoconv = tmp_path / "unoconv"
    fake_unoconv.write_text("x", encoding="utf-8")

    work = tmp_path / "work"
    work.mkdir()

    def fake_mkdtemp(prefix: str):
        out = work / "tmp"
        out.mkdir(exist_ok=True)
        return str(out)

    def fake_run(cmd, stdout=None, stderr=None, check=None, **kwargs):
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.write_bytes(b"pdf")

    monkeypatch.setattr(document_conversion, "find_libreoffice", lambda: None)
    monkeypatch.setattr(document_conversion, "find_unoconv", lambda: str(fake_unoconv))
    monkeypatch.setattr(document_conversion.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(document_conversion.subprocess, "run", fake_run)

    src = tmp_path / "input.pptx"
    src.write_bytes(b"pptx")

    pdf_path, temp_dir, tool = document_conversion.convert_to_pdf(src)
    assert pdf_path.exists()
    assert tool == "unoconv"
    assert temp_dir is not None


def test_find_unoconv_rejects_untrusted_path(monkeypatch):
    monkeypatch.setattr(document_conversion.shutil, "which", lambda _name: "/tmp/unoconv")
    monkeypatch.setattr(document_conversion, "_is_trusted_executable", lambda _p: False)
    assert document_conversion.find_unoconv() is None
