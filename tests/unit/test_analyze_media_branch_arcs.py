import logging
import shutil
from pathlib import Path

from packages.application import analyze_media
from packages.domain.pipeline_config import (
    KEY_ERROR_CODE,
    KEY_MIME,
    MEDIA_AUDIO,
    MEDIA_DOCX,
    MEDIA_PDF,
    ErrorCode,
)


def _ctx(tmp_path: Path, *, offline: bool) -> analyze_media.AnalyzeContext:
    return analyze_media.AnalyzeContext(
        input_dir=tmp_path,
        categories=["工作", "其他", "文档"],
        run_id="run-branch",
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
        audio_segment_threshold=10.0,
        audio_segment_seconds=5.0,
        audio_segment_count=1,
        audio_transcript_max_chars=200,
        doc_text_max_chars=200,
        sleep_s=0.0,
        offline=offline,
        model="gemini-test",
        api_key="key",
        max_file_mb=1024.0,
        image_prompt="image",
        doc_prompt="doc",
        audio_transcribe_prompt="audio",
        logger=logging.getLogger("test-analyze-branch"),
        cleanup_queue_path=tmp_path / "cleanup_uploads.jsonl",
        cleanup_queue_lock=analyze_media.threading.Lock(),
    )


def test_analyze_one_skips_size_gate_when_max_file_mb_disabled(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.pdf"
    p.write_bytes(b"pdf")
    ctx = _ctx(tmp_path, offline=True)
    ctx = ctx.__class__(**{**ctx.__dict__, "max_file_mb": 0.0})

    monkeypatch.setattr(analyze_media, "detect_media_type", lambda _path: MEDIA_PDF)
    row = analyze_media._analyze_one(p, ctx, lambda: None)
    assert row[KEY_MIME] == "application/pdf"


def test_analyze_one_offline_audio_sets_mime(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"audio")
    ctx = _ctx(tmp_path, offline=True)

    monkeypatch.setattr(analyze_media, "detect_media_type", lambda _path: MEDIA_AUDIO)
    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda _path: {"duration_s": 1.0})
    row = analyze_media._analyze_one(p, ctx, lambda: None)
    assert row.get(KEY_ERROR_CODE, "") == ""
    assert row[KEY_MIME].startswith("audio/")


def test_analyze_one_online_audio_metadata_error(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"audio")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "detect_media_type", lambda _path: MEDIA_AUDIO)
    monkeypatch.setattr(
        analyze_media,
        "extract_audio_fields",
        lambda _path: (_ for _ in ()).throw(RuntimeError("meta fail")),
    )
    row = analyze_media._analyze_one(p, ctx, lambda: object())
    assert row[KEY_ERROR_CODE] == ErrorCode.AUDIO_PREP_FAIL.value


def test_analyze_one_online_audio_duration_unknown_type(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"audio")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "detect_media_type", lambda _path: MEDIA_AUDIO)
    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda _path: {"duration_s": object()})
    monkeypatch.setattr(
        analyze_media,
        "prepare_audio_part",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("prep fail")),
    )
    row = analyze_media._analyze_one(p, ctx, lambda: object())
    assert row[KEY_ERROR_CODE] == ErrorCode.AUDIO_PREP_FAIL.value


def test_analyze_one_online_audio_duration_parse_exception(monkeypatch, tmp_path: Path):
    p = tmp_path / "b.wav"
    p.write_bytes(b"audio")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "detect_media_type", lambda _path: MEDIA_AUDIO)
    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda _path: {"duration_s": "bad-number"})
    monkeypatch.setattr(
        analyze_media,
        "prepare_audio_part",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("prep fail")),
    )
    row = analyze_media._analyze_one(p, ctx, lambda: object())
    assert row[KEY_ERROR_CODE] == ErrorCode.AUDIO_PREP_FAIL.value


def test_analyze_one_audio_segment_conf_warning(monkeypatch, tmp_path: Path):
    p = tmp_path / "c.wav"
    p.write_bytes(b"audio")
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "detect_media_type", lambda _path: MEDIA_AUDIO)
    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda _path: {"duration_s": 1.0})
    monkeypatch.setattr(analyze_media, "prepare_audio_part", lambda *_a, **_k: (object(), "audio/wav", None))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **_kwargs: ({"transcript": "你好", "language": "zh", "confidence": "bad"}, 0),
    )
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_text_with_retry",
        lambda **_kwargs: (
            {
                "kind": "音频",
                "category": "其他",
                "title": "标题",
                "tags": [],
                "confidence": 0.8,
                "notes": "",
            },
            0,
        ),
    )
    row = analyze_media._analyze_one(p, ctx, lambda: object())
    assert "transcript_warning" in row


def test_analyze_one_doc_prepare_cleanup_fail(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.docx"
    p.write_bytes(b"docx")
    pdf_path = tmp_path / "a.pdf"
    pdf_path.write_bytes(b"pdf")
    temp_dir = tmp_path / "tmp-doc"
    temp_dir.mkdir()
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "detect_media_type", lambda _path: MEDIA_DOCX)
    monkeypatch.setattr(analyze_media, "convert_to_pdf", lambda *_a, **_k: (pdf_path, temp_dir, "libreoffice"))
    monkeypatch.setattr(
        analyze_media,
        "build_file_part",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("prep fail")),
    )
    monkeypatch.setattr(shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cleanup fail")))

    row = analyze_media._analyze_one(p, ctx, lambda: object())
    assert row[KEY_ERROR_CODE] == ErrorCode.DOC_PREP_FAIL.value


def test_analyze_one_docx_sets_retry_and_warning(monkeypatch, tmp_path: Path):
    p = tmp_path / "a.docx"
    p.write_bytes(b"docx")
    pdf_path = tmp_path / "a.pdf"
    pdf_path.write_bytes(b"pdf")
    temp_dir = tmp_path / "tmp-doc-success"
    temp_dir.mkdir()
    ctx = _ctx(tmp_path, offline=False)

    monkeypatch.setattr(analyze_media, "detect_media_type", lambda _path: MEDIA_DOCX)
    monkeypatch.setattr(analyze_media, "convert_to_pdf", lambda *_a, **_k: (pdf_path, temp_dir, "libreoffice"))
    monkeypatch.setattr(analyze_media, "build_file_part", lambda *_a, **_k: (object(), "application/pdf", "upload-1"))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **_kwargs: (
            {
                "kind": "文档",
                "category": "文档",
                "title": "标题",
                "tags": [],
                "confidence": 0.8,
                "notes": "",
            },
            2,
        ),
    )
    monkeypatch.setattr(
        analyze_media,
        "sanitize_ai",
        lambda _raw, _cats: (
            {
                "kind": "文档",
                "category": "文档",
                "title": "标题",
                "tags": [],
                "confidence": 0.8,
                "notes": "",
            },
            ["normalized"],
        ),
    )
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *_a, **_k: True)

    row = analyze_media._analyze_one(p, ctx, lambda: object())
    assert row.get("ai_retry") == 2
    assert "normalized" in row.get("ai_warning", "")


def test_cleanup_orphaned_queues_missing_and_failure_paths(monkeypatch, tmp_path: Path):
    logger = logging.getLogger("cleanup-branch")
    events: list[str] = []

    def _capture_event(_logger, _level, event, _message, **_fields):
        events.append(event)

    monkeypatch.setattr(analyze_media, "log_event", _capture_event)

    missing_root = tmp_path / "missing"
    analyze_media._cleanup_orphaned_queues(missing_root, logger=logger, run_id="r1")

    queue_root = tmp_path / "queues"
    queue_root.mkdir()
    q = queue_root / "a.cleanup_uploads.jsonl"
    q.write_text("{}\n", encoding="utf-8")

    original_stat = analyze_media.Path.stat

    def _bad_stat(self: Path, *args, **kwargs):
        if self == q:
            raise OSError("stat fail")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(analyze_media.Path, "stat", _bad_stat)
    analyze_media._cleanup_orphaned_queues(queue_root, logger=logger, run_id="r2")
    assert "cleanup_orphan_queue_fail" in events

    original_resolve = analyze_media.Path.resolve

    def _bad_resolve(self: Path, *args, **kwargs):
        if self == queue_root:
            raise OSError("resolve fail")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(analyze_media.Path, "resolve", _bad_resolve)
    analyze_media._cleanup_orphaned_queues(queue_root, logger=logger, run_id="r3")
    assert "cleanup_orphan_scan_fail" in events


def test_cleanup_orphaned_queues_deletes_old_file_and_skips_dir(monkeypatch, tmp_path: Path):
    queue_root = tmp_path / "queues2"
    queue_root.mkdir()
    old_file = queue_root / "old.cleanup_uploads.jsonl"
    old_file.write_text("{}", encoding="utf-8")
    keep_dir = queue_root / "dir.cleanup_uploads.jsonl"
    keep_dir.mkdir()

    now_ts = old_file.stat().st_mtime + 7200
    monkeypatch.setattr(analyze_media.time, "time", lambda: now_ts)
    analyze_media._cleanup_orphaned_queues(queue_root, max_age_hours=1)

    assert not old_file.exists()
    assert keep_dir.exists()


def test_cleanup_orphaned_queues_outer_exception_without_logger(monkeypatch, tmp_path: Path):
    queue_root = tmp_path / "queues3"
    queue_root.mkdir()
    old_queue_file = queue_root / "old.cleanup_uploads.jsonl"
    old_queue_file.write_text("{}", encoding="utf-8")
    queue_dir_sentinel = queue_root / "dir.cleanup_uploads.jsonl"
    queue_dir_sentinel.mkdir()

    monkeypatch.setattr(
        analyze_media.time,
        "time",
        lambda: old_queue_file.stat().st_mtime + (25 * 3600),
    )

    original_resolve = analyze_media.Path.resolve

    def _bad_resolve(self: Path, *args, **kwargs):
        if self == queue_root:
            raise OSError("resolve fail")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(analyze_media.Path, "resolve", _bad_resolve)
    analyze_media._cleanup_orphaned_queues(queue_root, logger=None, run_id="r4")
    assert queue_root.exists()
    assert old_queue_file.exists()
    assert queue_dir_sentinel.exists()


def test_retry_cleanup_queue_logs_invalid_lines_summary(monkeypatch, tmp_path: Path):
    queue = tmp_path / "cleanup_uploads.jsonl"
    queue.write_text('bad-json\n{"name":"ok-1"}\nalso-bad\n', encoding="utf-8")

    events: list[str] = []

    def _capture_event(_logger, _level, event, _message, **_fields):
        events.append(event)

    monkeypatch.setattr(analyze_media, "log_event", _capture_event)
    monkeypatch.setattr(analyze_media, "safe_delete_file", lambda *_a, **_k: True)

    pending, recovered = analyze_media._retry_cleanup_queue(
        cleanup_queue_path=queue,
        offline=False,
        get_client=lambda: object(),
        logger=logging.getLogger("retry-branch"),
        timeout_s=1.0,
        run_id="run-q",
    )

    assert pending == 1
    assert recovered == 1
    assert "cleanup_queue_invalid_line" in events
    assert "cleanup_queue_invalid_lines_summary" in events
