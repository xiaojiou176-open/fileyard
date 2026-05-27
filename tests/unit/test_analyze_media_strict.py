import argparse
import sys
from pathlib import Path

from packages.application import analyze_media
from packages.infrastructure.manifest_store import read_jsonl_list


def _base_args(input_dir: Path, manifest: Path, csv: str = "", sleep: float = 0.0, fsync_interval: int = 0):
    return argparse.Namespace(
        input=str(input_dir),
        manifest=str(manifest),
        csv=csv,
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
        sleep=sleep,
        api_key="fake",
        fsync_interval=fsync_interval,
    )


def test_analyze_csv_warnings_and_retry(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    img = input_dir / "a.png"
    img.write_bytes(b"img")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "extract_exif_fields", lambda *a, **k: {})
    monkeypatch.setattr(analyze_media, "prepare_image_part", lambda *a, **k: (object(), "image/png", 10, 20, None))

    def fake_call(**kwargs):
        return {
            "kind": "audio",
            "category": "未知",
            "title": "abc测试",
            "tags": ["tag1", "标签"],
            "confidence": 0.9,
            "notes": "Hello世界",
        }, 2

    monkeypatch.setattr(analyze_media, "call_gemini_with_retry", fake_call)

    manifest = tmp_path / "manifest.jsonl"
    csv_path = tmp_path / "out.csv"
    args = _base_args(input_dir, manifest, csv=str(csv_path))

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    # 图片分支最终会强制为 截图/照片
    assert rows[0]["ai"]["kind"] == "照片"
    assert rows[0].get("ai_retry") == 2
    assert "Normalized kind" in rows[0].get("ai_warning", "")
    assert "Normalized tags" in rows[0].get("ai_warning", "")
    assert csv_path.exists()


def test_analyze_image_exif_error_and_dimensions(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    img = input_dir / "a.png"
    img.write_bytes(b"img")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(
        analyze_media,
        "extract_exif_fields",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("exif")),
    )
    monkeypatch.setattr(analyze_media, "prepare_image_part", lambda *a, **k: (object(), "image/png", 12, 34, None))
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
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0]["width"] == 12
    assert rows[0]["height"] == 34
    assert rows[0]["exif_datetime"] == ""


def test_analyze_audio_kind_normalization_appends_warning(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    audio = input_dir / "a.wav"
    audio.write_bytes(b"audio")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda *a, **k: {"duration_s": 1.0})
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
                "kind": "截图",
                "category": "工作",
                "title": "测试",
                "tags": ["x"],
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
    assert rows[0]["ai"]["kind"] == "音频"
    assert "Normalized kind" in rows[0].get("ai_warning", "")


def test_analyze_doc_kind_normalization(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    pdf = input_dir / "a.pdf"
    pdf.write_bytes(b"pdf")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "build_file_part", lambda *a, **k: (object(), "application/pdf", None))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **k: (
            {
                "kind": "照片",
                "category": "文档",
                "title": "报告",
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
    assert "Normalized kind" in rows[0].get("ai_warning", "")


def test_analyze_image_kind_normalization_exif(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    img = input_dir / "a.png"
    img.write_bytes(b"img")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(
        analyze_media,
        "extract_exif_fields",
        lambda *a, **k: {"exif_datetime": "2025-01-01T00:00:00"},
    )
    monkeypatch.setattr(
        analyze_media,
        "prepare_image_part",
        lambda *a, **k: (object(), "image/png", None, None, None),
    )
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **k: (
            {
                "kind": "文档",
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
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0]["ai"]["kind"] == "照片"
    assert "Normalized kind" in rows[0].get("ai_warning", "")


def test_analyze_sleep_and_fsync(monkeypatch, tmp_path: Path):
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

    # Patch time.sleep to avoid actual delay
    class DummyTime:
        @staticmethod
        def sleep(_):
            return None

    monkeypatch.setitem(sys.modules, "time", DummyTime)

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest, sleep=0.01, fsync_interval=2)

    analyze_media.cmd_analyze(args)
    assert manifest.exists()
