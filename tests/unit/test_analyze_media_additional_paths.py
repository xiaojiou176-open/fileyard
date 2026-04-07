import logging
from pathlib import Path

from packages.application import analyze_media
from packages.domain.pipeline_config import (
    AI_KIND,
    KEY_AI,
    KEY_ERROR_CODE,
    KEY_MEDIA_TYPE,
    KEY_TRANSCRIPT,
    KEY_TRANSCRIPT_CONF,
    KEY_TRANSCRIPT_LANG,
    MEDIA_AUDIO,
    MEDIA_IMAGE,
    ErrorCode,
)


def _ctx(tmp_path: Path, offline: bool, max_file_mb: float = 1024.0):
    return analyze_media.AnalyzeContext(
        input_dir=tmp_path,
        categories=["工作", "其他"],
        run_id="test_run",
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
        model="model",
        api_key="key",
        max_file_mb=max_file_mb,
        image_prompt="image",
        doc_prompt="doc",
        audio_transcribe_prompt="audio",
        logger=logging.getLogger("test"),
        cleanup_queue_path=tmp_path / "cleanup_queue.jsonl",
        cleanup_queue_lock=analyze_media.threading.Lock(),
    )


def test_build_offline_ai_variants(tmp_path: Path):
    audio = tmp_path / "a.wav"
    doc = tmp_path / "a.pdf"
    screenshot = tmp_path / "my_screenshot.png"
    photo = tmp_path / "photo.png"
    for p in (audio, doc, screenshot, photo):
        p.write_bytes(b"x")

    ai_audio = analyze_media._build_offline_ai(audio, MEDIA_AUDIO, ["其他"])
    ai_doc = analyze_media._build_offline_ai(doc, "pdf", ["其他"])
    ai_shot = analyze_media._build_offline_ai(screenshot, MEDIA_IMAGE, ["其他"])
    ai_photo = analyze_media._build_offline_ai(photo, MEDIA_IMAGE, ["其他"])

    assert ai_audio[AI_KIND] == "音频"
    assert ai_doc[AI_KIND] == "文档"
    assert ai_shot[AI_KIND] == "截图"
    assert ai_photo[AI_KIND] == "照片"


def test_analyze_one_file_too_large(tmp_path: Path):
    path = tmp_path / "big.png"
    path.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=True, max_file_mb=0.0000001)
    row = analyze_media._analyze_one(path, ctx, lambda: None)
    assert row[KEY_ERROR_CODE] == ErrorCode.FILE_TOO_LARGE.value


def test_analyze_one_stat_error(monkeypatch, tmp_path: Path):
    path = tmp_path / "bad.png"
    path.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=True, max_file_mb=1.0)

    monkeypatch.setattr(analyze_media, "_file_size_mb", lambda *_: (_ for _ in ()).throw(RuntimeError("stat")))
    row = analyze_media._analyze_one(path, ctx, lambda: None)
    assert row[KEY_ERROR_CODE] == ErrorCode.FILE_STAT_FAIL.value


def test_analyze_one_offline_exif_fail(monkeypatch, tmp_path: Path):
    path = tmp_path / "shot.png"
    path.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=True)

    monkeypatch.setattr(analyze_media, "extract_exif_fields", lambda *_: (_ for _ in ()).throw(RuntimeError("exif")))
    row = analyze_media._analyze_one(path, ctx, lambda: None)
    assert row["ai"]["kind"] in {"截图", "照片"}
    assert "offline" in row.get("ai_warning", "").lower()


def test_analyze_one_online_audio_success(monkeypatch, tmp_path: Path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda *_: {"duration_s": 5.0})
    monkeypatch.setattr(analyze_media, "plan_audio_segments", lambda *a, **k: [(0.0, 1.0)])
    monkeypatch.setattr(analyze_media, "extract_audio_segments", lambda *a, **k: ([(path, 0.0, 1.0)], None))
    monkeypatch.setattr(analyze_media, "prepare_audio_part", lambda *a, **k: (object(), None, "upload"))
    monkeypatch.setattr(analyze_media, "call_gemini_with_retry", lambda **k: ({"text": "ok"}, 0))
    monkeypatch.setattr(
        analyze_media,
        "extract_transcript_payload",
        lambda *_: {KEY_TRANSCRIPT: "你好", KEY_TRANSCRIPT_LANG: "zh", KEY_TRANSCRIPT_CONF: 0.9},
    )
    monkeypatch.setattr(analyze_media, "merge_transcript_segments", lambda *_: ("你好", "zh", 0.9))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_text_with_retry",
        lambda **k: (
            {
                "kind": "截图",
                "category": "工作",
                "title": "测试",
                "tags": [],
                "confidence": 0.9,
                "notes": "",
            },
            0,
        ),
    )
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *a, **k: True)

    row = analyze_media._analyze_one(path, ctx, lambda: object())
    assert row[KEY_MEDIA_TYPE] == MEDIA_AUDIO
    assert row[KEY_AI][AI_KIND] == "音频"


def test_analyze_one_audio_passes_timeout_settings(monkeypatch, tmp_path: Path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=False)

    captured: dict[str, float] = {}
    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda *_: {"duration_s": 5.0})
    monkeypatch.setattr(analyze_media, "plan_audio_segments", lambda *a, **k: [(0.0, 1.0)])

    def fake_extract_audio_segments(_path, _plan, timeout_s=0.0):
        captured["subprocess_timeout_s"] = timeout_s
        return [(path, 0.0, 1.0)], None

    monkeypatch.setattr(analyze_media, "extract_audio_segments", fake_extract_audio_segments)

    def fake_prepare_audio_part(*args, **kwargs):
        captured["prepare_audio_timeout_s"] = float(kwargs.get("timeout_s", -1))
        return object(), None, "upload"

    monkeypatch.setattr(analyze_media, "prepare_audio_part", fake_prepare_audio_part)
    monkeypatch.setattr(analyze_media, "call_gemini_with_retry", lambda **k: ({"text": "ok"}, 0))
    monkeypatch.setattr(
        analyze_media,
        "extract_transcript_payload",
        lambda *_: {KEY_TRANSCRIPT: "你好", KEY_TRANSCRIPT_LANG: "zh", KEY_TRANSCRIPT_CONF: 0.9},
    )
    monkeypatch.setattr(analyze_media, "merge_transcript_segments", lambda *_: ("你好", "zh", 0.9))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_text_with_retry",
        lambda **k: (
            {
                "kind": "截图",
                "category": "工作",
                "title": "测试",
                "tags": [],
                "confidence": 0.9,
                "notes": "",
            },
            0,
        ),
    )
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *a, **k: True)

    row = analyze_media._analyze_one(path, ctx, lambda: object())
    assert row[KEY_MEDIA_TYPE] == MEDIA_AUDIO
    assert captured["subprocess_timeout_s"] == ctx.subprocess_timeout_s
    assert captured["prepare_audio_timeout_s"] == ctx.ai_timeout_s


def test_analyze_one_docx_passes_timeout_settings(monkeypatch, tmp_path: Path):
    path = tmp_path / "a.docx"
    path.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=False)
    pdf_path = tmp_path / "a.pdf"
    pdf_path.write_bytes(b"x")

    captured: dict[str, float] = {}

    def fake_convert_to_pdf(_path, timeout_s=0.0):
        captured["convert_timeout_s"] = timeout_s
        return pdf_path, None, "libreoffice"

    def fake_build_file_part(_path, _client, _inline_max_mb, **kwargs):
        captured["build_timeout_s"] = float(kwargs.get("timeout_s", -1))
        return object(), "application/pdf", "upload"

    monkeypatch.setattr(analyze_media, "convert_to_pdf", fake_convert_to_pdf)
    monkeypatch.setattr(analyze_media, "build_file_part", fake_build_file_part)
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **k: (
            {
                "kind": "文档",
                "category": "工作",
                "title": "测试文档",
                "tags": [],
                "confidence": 0.9,
                "notes": "",
            },
            0,
        ),
    )
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *a, **k: True)

    row = analyze_media._analyze_one(path, ctx, lambda: object())
    assert not row.get(KEY_ERROR_CODE, "")
    assert captured["convert_timeout_s"] == ctx.subprocess_timeout_s
    assert captured["build_timeout_s"] == ctx.ai_timeout_s


def test_analyze_one_online_docx_convert_fail(monkeypatch, tmp_path: Path):
    path = tmp_path / "a.docx"
    path.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "convert_to_pdf", lambda *_, **__: (_ for _ in ()).throw(RuntimeError("convert")))
    row = analyze_media._analyze_one(path, ctx, lambda: object())
    assert row[KEY_ERROR_CODE] == ErrorCode.DOC_CONVERT_FAIL.value


def test_analyze_one_online_image_prep_fail(monkeypatch, tmp_path: Path):
    path = tmp_path / "a.png"
    path.write_bytes(b"x")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "extract_exif_fields", lambda *_: {})
    monkeypatch.setattr(
        analyze_media,
        "prepare_image_part",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("prep")),
    )

    row = analyze_media._analyze_one(path, ctx, lambda: object())
    assert row[KEY_ERROR_CODE] == ErrorCode.IMAGE_PREP_FAIL.value
