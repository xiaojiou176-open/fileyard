import argparse
from pathlib import Path

from packages.application import analyze_media
from packages.domain.pipeline_config import ErrorCode
from packages.infrastructure.manifest_store import read_jsonl_list


def _base_args(tmp_path: Path, input_dir: Path, manifest: Path):
    return argparse.Namespace(
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
        audio_segment_threshold=600.0,
        audio_segment_seconds=30.0,
        audio_segment_count=1,
        audio_transcript_max_chars=4000,
        doc_text_max_chars=6000,
        sleep=0.0,
        api_key="fake",
        fsync_interval=0,
    )


def test_cmd_analyze_pdf_build_file_part_error(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    pdf = input_dir / "a.pdf"
    pdf.write_bytes(b"pdf")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(
        analyze_media,
        "build_file_part",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(tmp_path, input_dir, manifest)

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert "Document preparation error" in (rows[0].get("error") or "")


def test_cmd_analyze_docx_convert_error(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    docx = input_dir / "a.docx"
    docx.write_bytes(b"docx")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "convert_to_pdf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("conv")))

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(tmp_path, input_dir, manifest)

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert "Document-to-PDF conversion failed" in (rows[0].get("error") or "")


def test_cmd_analyze_image_prepare_error(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    img = input_dir / "a.png"
    img.write_bytes(b"img")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(
        analyze_media,
        "prepare_image_part",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad")),
    )
    monkeypatch.setattr(analyze_media, "extract_exif_fields", lambda *a, **k: {})

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(tmp_path, input_dir, manifest)

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert "Image preparation error" in (rows[0].get("error") or "")


def test_cmd_analyze_image_prepare_timeout_maps_to_ai_timeout(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    img = input_dir / "a.png"
    img.write_bytes(b"img")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(
        analyze_media,
        "prepare_image_part",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("operation timed out")),
    )
    monkeypatch.setattr(analyze_media, "extract_exif_fields", lambda *a, **k: {})

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(tmp_path, input_dir, manifest)

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0].get("error_code") == ErrorCode.AI_TIMEOUT.value
