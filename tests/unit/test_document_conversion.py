import pytest

from packages.infrastructure import document_conversion


def test_convert_to_pdf_missing_tools(monkeypatch, tmp_path):
    def _none():
        return None

    monkeypatch.setattr(document_conversion, "find_libreoffice", _none)
    monkeypatch.setattr(document_conversion, "find_unoconv", _none)

    src = tmp_path / "a.docx"
    src.write_bytes(b"dummy")

    with pytest.raises(RuntimeError):
        document_conversion.convert_to_pdf(src)
