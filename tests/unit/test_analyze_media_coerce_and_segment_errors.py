import argparse
import logging
import shutil
from pathlib import Path

import pytest

from packages.application import analyze_media
from packages.domain.pipeline_config import KEY_AI, KEY_ERROR_CODE, KEY_MIME, ErrorCode


def _ctx(tmp_path: Path, *, offline: bool) -> analyze_media.AnalyzeContext:
    return analyze_media.AnalyzeContext(
        input_dir=tmp_path,
        categories=["工作", "其他"],
        run_id="run-f",
        generator_version="4.0.0",
        schema_version=2,
        fsync_interval=0,
        inline_max_mb=15.0,
        resize_max_side=0,
        max_retries=1,
        retry_base_s=0.1,
        retry_max_s=1.0,
        ai_timeout_s=1.0,
        subprocess_timeout_s=1.0,
        audio_segment_threshold=1.0,
        audio_segment_seconds=1.0,
        audio_segment_count=1,
        audio_transcript_max_chars=100,
        doc_text_max_chars=100,
        sleep_s=0.0,
        offline=offline,
        model="gemini-test",
        api_key="key",
        max_file_mb=1024.0,
        image_prompt="image",
        doc_prompt="doc",
        audio_transcribe_prompt="audio",
        logger=logging.getLogger("test"),
        cleanup_queue_path=tmp_path / "cleanup_uploads.jsonl",
        cleanup_queue_lock=analyze_media.threading.Lock(),
    )


def _args(input_dir: Path, manifest: Path, **extra):
    base = dict(
        input=str(input_dir),
        manifest=str(manifest),
        csv="",
        report="",
        chunk_size=100,
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
        log_level="INFO",
        log_json=False,
        run_id="run-f-cmd",
        generator_version="4.0.0",
        max_file_mb=1024.0,
        max_files=0,
        max_total_mb=0.0,
        workers=1,
        offline=True,
        ai_timeout_s=1.0,
        subprocess_timeout_s=1.0,
        durability="none",
    )
    base.update(extra)
    return argparse.Namespace(**base)


def test_sanitize_and_coerce_confidence_edge_cases() -> None:
    cleaned, warnings = analyze_media.sanitize_ai(
        {
            "kind": "截图",
            "category": "其他",
            "title": "测试",
            "tags": [],
            "confidence": "abc",
            "notes": "",
        },
        ["工作", "其他"],
    )
    assert cleaned["confidence"] == 0.0
    assert any("non-numeric string" in item for item in warnings)

    coerce_warnings: list[str] = []
    assert (
        analyze_media._coerce_confidence(
            3.2,
            field_name="merged_transcript_confidence",
            warnings=coerce_warnings,
            default_value=0.0,
        )
        == 0.0
    )
    assert any("out of range" in item for item in coerce_warnings)


def test_analyze_one_offline_audio_error_and_pdf_mime(monkeypatch, tmp_path: Path) -> None:
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=True)

    monkeypatch.setattr(
        analyze_media,
        "extract_audio_fields",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    row_audio = analyze_media._analyze_one(audio, ctx, lambda: None)
    assert row_audio[KEY_ERROR_CODE] == ErrorCode.AUDIO_PREP_FAIL.value

    row_pdf = analyze_media._analyze_one(pdf, ctx, lambda: None)
    assert row_pdf[KEY_MIME] == "application/pdf"


def test_analyze_one_online_audio_segment_error_paths(monkeypatch, tmp_path: Path) -> None:
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda *_a, **_k: {"duration_s": 12.0})
    monkeypatch.setattr(analyze_media, "plan_audio_segments", lambda *_a, **_k: [(0.0, 1.0)])
    monkeypatch.setattr(
        analyze_media,
        "extract_audio_segments",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("segment-fail")),
    )

    row = analyze_media._analyze_one(audio, ctx, lambda: object())
    assert row[KEY_ERROR_CODE] == ErrorCode.AUDIO_PREP_FAIL.value


def test_analyze_one_audio_warning_retry_and_cleanup_fail(monkeypatch, tmp_path: Path) -> None:
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    temp_dir = tmp_path / "tmp-segments"
    temp_dir.mkdir()

    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda *_a, **_k: {"duration_s": 12.0})
    monkeypatch.setattr(analyze_media, "plan_audio_segments", lambda *_a, **_k: [(0.0, 1.0)])
    monkeypatch.setattr(analyze_media, "extract_audio_segments", lambda *_a, **_k: ([(audio, 0.0, 1.0)], temp_dir))
    monkeypatch.setattr(analyze_media, "prepare_audio_part", lambda *_a, **_k: (object(), "audio/wav", "upload-1"))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **_kwargs: ({"text": "ok", "language": "zh", "confidence": "bad"}, 0),
    )
    monkeypatch.setattr(
        analyze_media,
        "extract_transcript_payload",
        lambda *_a, **_k: {"transcript": "你好", "language": "zh", "confidence": "bad", "notes": ""},
    )
    monkeypatch.setattr(analyze_media, "merge_transcript_segments", lambda *_a, **_k: ("你好", "zh", 1.8))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_text_with_retry",
        lambda **_kwargs: (
            {
                "kind": "截图",
                "category": "其他",
                "title": "标题",
                "tags": [],
                "confidence": 0.8,
                "notes": "",
            },
            2,
        ),
    )
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *_a, **_k: True)
    monkeypatch.setattr(shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cleanup-fail")))

    row = analyze_media._analyze_one(audio, ctx, lambda: object())
    assert row.get(KEY_ERROR_CODE, "") == ""
    assert "transcript_warning" in row
    assert row.get("ai_retry") == 2


def test_analyze_one_pdf_retry_warning_and_queue(monkeypatch, tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "build_file_part", lambda *_a, **_k: (object(), "application/pdf", "upload-pdf"))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **_kwargs: (
            {
                "kind": "截图",
                "category": "未知",
                "title": "标题",
                "tags": [],
                "confidence": 0.7,
                "notes": "",
            },
            3,
        ),
    )
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *_a, **_k: False)

    row = analyze_media._analyze_one(pdf, ctx, lambda: object())
    assert row[KEY_AI]["kind"] == "文档"
    assert row.get("ai_retry") == 3
    assert "ai_warning" in row
    assert ctx.cleanup_queue_path.exists()


def test_analyze_one_docx_cleanup_paths(monkeypatch, tmp_path: Path) -> None:
    docx = tmp_path / "a.docx"
    docx.write_bytes(b"x")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"x")
    temp_dir = tmp_path / "temp-doc"
    temp_dir.mkdir()

    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "convert_to_pdf", lambda *_a, **_k: (pdf, temp_dir, "libreoffice"))
    monkeypatch.setattr(analyze_media, "build_file_part", lambda *_a, **_k: (object(), "application/pdf", "upload-doc"))
    monkeypatch.setattr(analyze_media, "call_gemini_with_retry", lambda **_k: (_ for _ in ()).throw(RuntimeError("ai-fail")))
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *_a, **_k: False)
    monkeypatch.setattr(shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cleanup")))

    row = analyze_media._analyze_one(docx, ctx, lambda: object())
    assert row[KEY_ERROR_CODE] == ErrorCode.AI_FAIL.value
    assert ctx.cleanup_queue_path.exists()


def test_analyze_one_doc_unsupported_format(monkeypatch, tmp_path: Path) -> None:
    bad = tmp_path / "a.txt"
    bad.write_text("x", encoding="utf-8")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "detect_media_type", lambda *_a, **_k: "doc")
    monkeypatch.setattr(
        analyze_media,
        "convert_to_pdf",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("convert-fail")),
    )
    row = analyze_media._analyze_one(bad, ctx, lambda: object())
    assert row[KEY_ERROR_CODE] == ErrorCode.DOC_CONVERT_FAIL.value


def test_analyze_one_image_delete_fail_queues_upload(monkeypatch, tmp_path: Path) -> None:
    image = tmp_path / "a.png"
    image.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "extract_exif_fields", lambda *_a, **_k: {})
    monkeypatch.setattr(analyze_media, "prepare_image_part", lambda *_a, **_k: (object(), "image/png", None, None, "upload-img"))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **_kwargs: (
            {
                "kind": "截图",
                "category": "其他",
                "title": "标题",
                "tags": [],
                "confidence": 0.8,
                "notes": "",
            },
            0,
        ),
    )
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *_a, **_k: False)

    row = analyze_media._analyze_one(image, ctx, lambda: object())
    assert row.get(KEY_ERROR_CODE, "") == ""
    assert ctx.cleanup_queue_path.exists()


def test_cmd_analyze_normalizes_limits_and_reports(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"
    report = tmp_path / "report.json"

    monkeypatch.setattr(analyze_media, "resolve_fsync_interval", lambda *_a, **_k: -5)
    captured: dict[str, object] = {}

    monkeypatch.setattr(analyze_media, "count_media_files", lambda _path: 1)
    monkeypatch.setattr(
        analyze_media,
        "_analyze_one",
        lambda _path, _ctx, _get_client: {
            "path": str(_path),
            "media_type": "image",
            "ai": {
                "kind": "照片",
                "category": "其他",
                "title": "未命名",
                "tags": [],
                "confidence": 0.0,
                "notes": "",
            },
            "error": "",
        },
    )
    monkeypatch.setattr(analyze_media, "build_client", lambda _api_key: object())

    def _fake_cleanup(**kwargs):
        captured["client"] = kwargs["get_client"]()
        return 0, 0

    monkeypatch.setattr(analyze_media, "_retry_cleanup_queue", _fake_cleanup)

    args = _args(
        input_dir,
        manifest,
        report=str(report),
        chunk_size=0,
        max_files=-1,
        max_total_mb=-1.0,
        workers=0,
        ai_timeout_s=0,
        subprocess_timeout_s=0,
        offline=False,
    )
    analyze_media.cmd_analyze(args)

    assert manifest.exists()
    assert report.exists()
    assert captured["client"] is not None


def test_cmd_analyze_preflight_scan_fail(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    manifest = tmp_path / "manifest.jsonl"

    monkeypatch.setattr(
        analyze_media,
        "scan_media_stats",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("scan-fail")),
    )

    args = _args(input_dir, manifest, max_files=1, max_total_mb=1.0, offline=True)
    with pytest.raises(SystemExit, match="Preflight failed"):
        analyze_media.cmd_analyze(args)


def test_cmd_analyze_preflight_exceeded(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    manifest = tmp_path / "manifest.jsonl"

    monkeypatch.setattr(analyze_media, "scan_media_stats", lambda *_a, **_k: (10, 9.9, True))

    args = _args(input_dir, manifest, max_files=1, max_total_mb=1.0, offline=True)
    with pytest.raises(SystemExit, match="Preflight limit exceeded"):
        analyze_media.cmd_analyze(args)


def test_retry_cleanup_queue_empty_names_and_all_success(tmp_path: Path, monkeypatch) -> None:
    empty_queue = tmp_path / "cleanup-empty.jsonl"
    empty_queue.write_text('\n{}\n{"name": ""}\n', encoding="utf-8")

    pending, recovered = analyze_media._retry_cleanup_queue(
        cleanup_queue_path=empty_queue,
        offline=False,
        get_client=lambda: object(),
        logger=logging.getLogger("test"),
        timeout_s=1.0,
        run_id="run-f",
    )
    assert pending == 0
    assert recovered == 0
    assert empty_queue.exists()

    queue = tmp_path / "cleanup-ok.jsonl"
    queue.write_text('{"name":"ok-1"}\n{"name":"ok-2"}\n', encoding="utf-8")
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *_a, **_k: True)

    pending2, recovered2 = analyze_media._retry_cleanup_queue(
        cleanup_queue_path=queue,
        offline=False,
        get_client=lambda: object(),
        logger=logging.getLogger("test"),
        timeout_s=1.0,
        run_id="run-f",
    )
    assert pending2 == 2
    assert recovered2 == 2
    assert not queue.exists()
