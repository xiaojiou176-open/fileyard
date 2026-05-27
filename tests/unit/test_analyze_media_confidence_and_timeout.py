import logging
from pathlib import Path

from packages.application import analyze_media
from packages.domain.pipeline_config import (
    AI_KIND,
    KEY_AI,
    KEY_ERROR_CODE,
    KEY_MEDIA_TYPE,
    MEDIA_AUDIO,
    MEDIA_IMAGE,
    ErrorCode,
)


def _ctx(tmp_path: Path, offline: bool = False):
    return analyze_media.AnalyzeContext(
        input_dir=tmp_path,
        categories=["工作", "其他"],
        run_id="run-c",
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
        audio_segment_threshold=999.0,
        audio_segment_seconds=1.0,
        audio_segment_count=1,
        audio_transcript_max_chars=100,
        doc_text_max_chars=100,
        sleep_s=0.0,
        offline=offline,
        model="model",
        api_key="key",
        max_file_mb=1024.0,
        image_prompt="image",
        doc_prompt="doc",
        audio_transcribe_prompt="audio",
        logger=logging.getLogger("test"),
        cleanup_queue_path=tmp_path / "cleanup_uploads.jsonl",
        cleanup_queue_lock=analyze_media.threading.Lock(),
    )


def test_sanitize_ai_confidence_and_warnings_branches():
    cleaned, warnings = analyze_media.sanitize_ai(
        {
            "kind": "unknown-kind",
            "category": "unknown-category",
            "title": "abc测试123",
            "tags": ["tag1", "标签", ""],
            "confidence": "",
            "notes": "note说明",
            "unexpected": "x",
        },
        ["工作", "其他"],
    )
    assert cleaned["title"] == "测试"
    assert cleaned["tags"] == ["标签"]
    assert cleaned["confidence"] == 0.0
    assert any("Dropped unsupported fields" in x for x in warnings)
    assert any("Missing confidence" in x for x in warnings)

    cleaned2, warnings2 = analyze_media.sanitize_ai(
        {
            "kind": "截图",
            "category": "其他",
            "title": "测试",
            "tags": [],
            "confidence": True,
            "notes": "",
        },
        ["工作", "其他"],
    )
    assert cleaned2["confidence"] == 0.0
    assert any("Invalid confidence type: bool" in x for x in warnings2)

    cleaned3, warnings3 = analyze_media.sanitize_ai(
        {
            "kind": "截图",
            "category": "其他",
            "title": "测试",
            "tags": [],
            "confidence": "2.5",
            "notes": "",
        },
        ["工作", "其他"],
    )
    assert cleaned3["confidence"] == 0.0
    assert any("Confidence out of range" in x for x in warnings3)


def test_is_timeout_error_and_queue_failed_upload(tmp_path: Path):
    assert analyze_media._is_timeout_error(TimeoutError("x")) is True
    assert analyze_media._is_timeout_error(RuntimeError("request timed out")) is True

    class _StatusError(Exception):
        def __init__(self, message: str, status_code: int):
            super().__init__(message)
            self.status_code = status_code

    status_exc = _StatusError("gateway", 504)
    assert analyze_media._is_timeout_error(status_exc) is True

    class _CodeError(Exception):
        def __init__(self, message: str, code: str):
            super().__init__(message)
            self.code = code

    code_exc = _CodeError("timeout code", "408")
    assert analyze_media._is_timeout_error(code_exc) is True

    class _Resp:
        status_code = 504

    class _ResponseError(Exception):
        def __init__(self, message: str):
            super().__init__(message)
            self.response = _Resp()

    response_exc = _ResponseError("response status")
    assert analyze_media._is_timeout_error(response_exc) is True

    assert analyze_media._is_timeout_error(RuntimeError("普通错误")) is False

    ctx = _ctx(tmp_path)
    analyze_media._queue_failed_upload(ctx, "")
    assert not ctx.cleanup_queue_path.exists()

    analyze_media._queue_failed_upload(ctx, "upload-1")
    lines = ctx.cleanup_queue_path.read_text(encoding="utf-8").splitlines()
    assert lines and "upload-1" in lines[0]


def test_analyze_one_audio_transcribe_timeout_queues_upload(monkeypatch, tmp_path: Path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda *_: {"duration_s": 1.0})
    monkeypatch.setattr(analyze_media, "prepare_audio_part", lambda *a, **k: (object(), "audio/wav", "upload-a"))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("timed out")),
    )
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *_a, **_k: False)

    row = analyze_media._analyze_one(path, ctx, lambda: object())

    assert row[KEY_MEDIA_TYPE] == MEDIA_AUDIO
    assert row[KEY_ERROR_CODE] == ErrorCode.AI_TIMEOUT.value
    queue_text = ctx.cleanup_queue_path.read_text(encoding="utf-8")
    assert "upload-a" in queue_text


def test_analyze_one_image_kind_forced_by_filename(monkeypatch, tmp_path: Path):
    path = tmp_path / "my_screenshot.png"
    path.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "extract_exif_fields", lambda *_: {})
    monkeypatch.setattr(
        analyze_media,
        "prepare_image_part",
        lambda *a, **k: (object(), "image/png", None, None, "upload-img"),
    )
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **_k: (
            {
                "kind": "文档",
                "category": "其他",
                "title": "标题",
                "tags": [],
                "confidence": 0.9,
                "notes": "",
            },
            1,
        ),
    )
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *_a, **_k: True)

    row = analyze_media._analyze_one(path, ctx, lambda: object())

    assert row[KEY_MEDIA_TYPE] == MEDIA_IMAGE
    assert row[KEY_AI][AI_KIND] == "截图"
    assert "Normalized kind" in row.get("ai_warning", "")
