import argparse
from pathlib import Path

from packages.application import analyze_media
from packages.infrastructure.manifest_store import read_jsonl_list


def _base_args(input_dir: Path, manifest: Path, fsync_interval: int = 0):
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
        audio_segment_threshold=10.0,
        audio_segment_seconds=5.0,
        audio_segment_count=2,
        audio_transcript_max_chars=4000,
        doc_text_max_chars=6000,
        sleep=0.0,
        api_key="fake",
        fsync_interval=fsync_interval,
    )


def test_cmd_analyze_empty_directory(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)
    assert not manifest.exists()


def test_cmd_analyze_fsync_interval_negative(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    img = input_dir / "a.png"
    img.write_bytes(b"img")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(
        analyze_media,
        "prepare_image_part",
        lambda *a, **k: (object(), "image/png", None, None, None),
    )
    monkeypatch.setattr(analyze_media, "extract_exif_fields", lambda *a, **k: {})
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **k: (
            {
                "kind": "截图",
                "category": "工作",
                "title": "测试",
                "tags": [],
                "confidence": 1,
                "notes": "",
            },
            0,
        ),
    )

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest, fsync_interval=-5)

    analyze_media.cmd_analyze(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert len(rows) == 1


def test_cmd_analyze_pdf_success(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    pdf = input_dir / "a.pdf"
    pdf.write_bytes(b"pdf")

    deleted = []

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "build_file_part", lambda *a, **k: (object(), "application/pdf", "files/1"))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **k: (
            {
                "kind": "文档",
                "category": "文档",
                "title": "报告",
                "tags": [],
                "confidence": 0.9,
                "notes": "",
            },
            0,
        ),
    )

    def _fake_safe_delete_file(client, name, logger=None, **kwargs):
        deleted.append(name)
        return True

    monkeypatch.setattr(analyze_media, "safe_delete_file", _fake_safe_delete_file)

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0]["ai"]["kind"] == "文档"
    assert "files/1" in deleted


def test_cmd_analyze_docx_success(monkeypatch, tmp_path: Path):
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
    monkeypatch.setattr(analyze_media, "build_file_part", lambda *a, **k: (object(), "application/pdf", None))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **k: (
            {
                "kind": "文档",
                "category": "文档",
                "title": "文档",
                "tags": [],
                "confidence": 0.9,
                "notes": "",
            },
            0,
        ),
    )

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0]["ai"]["kind"] == "文档"
    assert not temp_dir.exists()


def test_cmd_analyze_image_ai_error(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    img = input_dir / "a.png"
    img.write_bytes(b"img")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "extract_exif_fields", lambda *a, **k: {})
    monkeypatch.setattr(
        analyze_media,
        "prepare_image_part",
        lambda *a, **k: (object(), "image/png", None, None, None),
    )
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **k: (_ for _ in ()).throw(RuntimeError("ai")),
    )

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert "AI error" in (rows[0].get("error") or "")


def test_cmd_analyze_audio_segment_warning(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    audio = input_dir / "a.wav"
    audio.write_bytes(b"audio")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda *a, **k: {"duration_s": 100.0})
    monkeypatch.setattr(analyze_media, "extract_audio_segments", lambda *a, **k: ([], None))
    monkeypatch.setattr(analyze_media, "prepare_audio_part", lambda *a, **k: (object(), "audio/wav", None))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **k: ({"transcript": "你好", "language": "中文", "confidence": 0.9, "notes": ""}, 0),
    )
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_text_with_retry",
        lambda **k: (
            {
                "kind": "音频",
                "category": "其他",
                "title": "测试",
                "tags": [],
                "confidence": 0.8,
                "notes": "",
            },
            0,
        ),
    )

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert "audio_warning" in rows[0]
