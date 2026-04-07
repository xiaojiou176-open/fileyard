import argparse
from pathlib import Path

from packages.application import analyze_media
from packages.infrastructure.manifest_store import read_jsonl_list


def test_docx_build_file_part_error_cleans_temp(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    docx = input_dir / "a.docx"
    docx.write_bytes(b"docx")

    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    pdf_path = temp_dir / "a.pdf"
    pdf_path.write_bytes(b"pdf")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "convert_to_pdf", lambda *a, **k: (pdf_path, temp_dir, "libreoffice"))
    monkeypatch.setattr(
        analyze_media,
        "build_file_part",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fail")),
    )

    manifest = tmp_path / "manifest.jsonl"
    args = argparse.Namespace(
        input=str(input_dir),
        manifest=str(manifest),
        csv="",
        model="gemini-test",
        categories=["工作", "其他", "文档"],
        inline_max_mb=15.0,
        resize_max_side=0,
        max_retries=1,
        retry_base_s=0.1,
        retry_max_s=0.1,
        audio_segment_threshold=10.0,
        audio_segment_seconds=5.0,
        audio_segment_count=1,
        audio_transcript_max_chars=4000,
        doc_text_max_chars=6000,
        sleep=0.0,
        api_key="fake",
        fsync_interval=0,
    )

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert "Document preparation error" in (rows[0].get("error") or "")
    assert not temp_dir.exists()
