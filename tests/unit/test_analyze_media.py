import argparse
import hashlib
from pathlib import Path

from packages.application import analyze_media, core_utils
from packages.infrastructure.manifest_store import read_jsonl_list


def test_sha1_file_stops_at_eof_and_matches_digest(monkeypatch):
    data = b"abc"
    expected = hashlib.sha1(data, usedforsecurity=False).hexdigest()

    class _FakeFile:
        def __init__(self):
            self._reads = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _chunk_size):
            self._reads += 1
            if self._reads == 1:
                return data
            if self._reads == 2:
                return b""
            raise AssertionError("sha1_file() read after EOF")

    fake_file = _FakeFile()
    monkeypatch.setattr(Path, "open", lambda self, mode: fake_file)

    digest = core_utils.sha1_file(Path("dummy.bin"), chunk_size=2)

    assert digest == expected


def test_cmd_analyze_streaming(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    img = input_dir / "a.png"
    aud = input_dir / "b.wav"
    pdf = input_dir / "c.pdf"
    docx = input_dir / "d.docx"
    img.write_bytes(b"img")
    aud.write_bytes(b"aud")
    pdf.write_bytes(b"pdf")
    docx.write_bytes(b"docx")

    dummy_client = object()

    def fake_build_client(api_key: str):
        return dummy_client

    def fake_prepare_image_part(path, client, inline_max_mb, resize_max_side, **kwargs):
        return object(), "image/png", None, None, None

    def fake_prepare_audio_part(path, client, inline_max_mb, **kwargs):
        return object(), "audio/wav", None

    def fake_build_file_part(path, client, inline_max_mb, **kwargs):
        return object(), "application/pdf", None

    def fake_extract_exif_fields(path):
        return {}

    def fake_convert_to_pdf(path, **kwargs):
        pdf_path = tmp_path / "converted.pdf"
        pdf_path.write_bytes(b"pdf")
        temp_dir = tmp_path / "temp_dir"
        temp_dir.mkdir(exist_ok=True)
        return pdf_path, temp_dir, "libreoffice"

    def fake_call_gemini_with_retry(client, model, image_part, prompt, max_retries, retry_base_s, retry_max_s, **kwargs):
        if '"transcript": "Transcribed text"' in prompt:
            return {"transcript": "你好", "language": "中文", "confidence": 0.9, "notes": ""}, 0
        if '"kind": "文档"' in prompt:
            return {
                "kind": "文档",
                "category": "文档",
                "title": "测试文档",
                "tags": ["标签"],
                "confidence": 0.9,
                "notes": "",
            }, 0
        if '"kind": "音频"' in prompt:
            return {
                "kind": "音频",
                "category": "其他",
                "title": "测试音频",
                "tags": [],
                "confidence": 0.9,
                "notes": "",
            }, 0
        return {
            "kind": "截图",
            "category": "工作",
            "title": "测试图片",
            "tags": ["标签"],
            "confidence": 0.9,
            "notes": "",
        }, 0

    def fake_call_gemini_text_with_retry(client, model, prompt, max_retries, retry_base_s, retry_max_s, **kwargs):
        return {
            "kind": "音频",
            "category": "其他",
            "title": "测试音频",
            "tags": [],
            "confidence": 0.9,
            "notes": "",
        }, 0

    monkeypatch.setattr(analyze_media, "build_client", fake_build_client)
    monkeypatch.setattr(analyze_media, "prepare_image_part", fake_prepare_image_part)
    monkeypatch.setattr(analyze_media, "prepare_audio_part", fake_prepare_audio_part)
    monkeypatch.setattr(analyze_media, "build_file_part", fake_build_file_part)
    monkeypatch.setattr(analyze_media, "extract_exif_fields", fake_extract_exif_fields)
    monkeypatch.setattr(analyze_media, "convert_to_pdf", fake_convert_to_pdf)
    monkeypatch.setattr(analyze_media, "call_gemini_with_retry", fake_call_gemini_with_retry)
    monkeypatch.setattr(analyze_media, "call_gemini_text_with_retry", fake_call_gemini_text_with_retry)

    manifest = tmp_path / "manifest.jsonl"

    args = argparse.Namespace(
        input=str(input_dir),
        manifest=str(manifest),
        csv="",
        model="gemini-test",
        categories=["工作", "文档", "其他"],
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

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert len(rows) == 4
    for row in rows:
        assert row.get("input_root") == str(input_dir)
        assert row.get("media_type")
