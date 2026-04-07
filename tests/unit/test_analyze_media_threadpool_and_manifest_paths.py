import argparse
import logging
import time
from pathlib import Path

import pytest

from packages.application import analyze_media
from packages.infrastructure.manifest_store import read_jsonl_list


def _base_args(input_dir: Path, manifest: Path):
    return argparse.Namespace(
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
        run_id="run-e",
        generator_version="4.0.0",
        max_file_mb=1024.0,
        workers=1,
        offline=True,
    )


def test_cmd_analyze_threadpool_branch_and_tail_fsync(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(b"a")
    (input_dir / "b.png").write_bytes(b"b")

    fsync_calls: list[int] = []
    monkeypatch.setattr(analyze_media.os, "fsync", lambda fd: fsync_calls.append(fd))

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)
    args.workers = 2
    args.fsync_interval = 3

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert len(rows) == 2
    assert len(fsync_calls) == 1


def test_cmd_analyze_threadpool_preserves_manifest_input_order(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for name in ("a.png", "b.png", "c.png"):
        (input_dir / name).write_bytes(name.encode("utf-8"))

    sleep_map = {"a.png": 0.12, "b.png": 0.06, "c.png": 0.0}

    def fake_analyze_one(path: Path, ctx, get_client):
        _ = (ctx, get_client)
        time.sleep(sleep_map[path.name])
        return {
            "path": str(path),
            "media_type": "image",
            "ai": {
                "kind": "截图",
                "category": "其他",
                "title": path.stem,
                "tags": [],
                "confidence": 0.9,
                "notes": "",
            },
        }

    monkeypatch.setattr(analyze_media, "_analyze_one", fake_analyze_one)

    manifest = tmp_path / "manifest_order.jsonl"
    args = _base_args(input_dir, manifest)
    args.workers = 2

    analyze_media.cmd_analyze(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert [Path(row["path"]).name for row in rows] == ["a.png", "b.png", "c.png"]


def test_cmd_analyze_manifest_cleanup_fail_then_exit(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(b"img")

    monkeypatch.setattr(analyze_media, "write_jsonl_line", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("write failed")))

    original_unlink = Path.unlink

    def _patched_unlink(self: Path, *args, **kwargs):
        if str(self).endswith(".partial"):
            raise OSError("unlink failed")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _patched_unlink)

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    with pytest.raises(SystemExit, match="Failed to write manifest"):
        analyze_media.cmd_analyze(args)


def test_cmd_analyze_manifest_replace_failure(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(b"img")

    original_replace = Path.replace

    def _patched_replace(self: Path, target):
        if str(self).endswith(".partial"):
            raise OSError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _patched_replace)

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    with pytest.raises(SystemExit, match="Failed to update manifest"):
        analyze_media.cmd_analyze(args)


def test_cmd_analyze_csv_write_failure(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(b"img")

    monkeypatch.setattr(
        analyze_media,
        "write_csv_from_manifest",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("csv failed")),
    )

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)
    args.csv = str(tmp_path / "out.csv")

    with pytest.raises(SystemExit, match="Failed to write CSV"):
        analyze_media.cmd_analyze(args)


def test_cmd_analyze_report_write_failure(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(b"img")

    monkeypatch.setattr(
        analyze_media,
        "write_report",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("report failed")),
    )

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)
    args.report = str(tmp_path / "report.json")

    with pytest.raises(SystemExit, match="Failed to write report"):
        analyze_media.cmd_analyze(args)


def test_retry_cleanup_queue_retains_failed_uploads(tmp_path: Path, monkeypatch):
    queue = tmp_path / "cleanup_uploads.jsonl"
    queue.write_text(
        "\n".join(
            [
                "not-json",
                '{"name": "ok-1"}',
                '{"name": ""}',
                '{"name": "fail-1"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    deleted: list[str] = []

    def _safe_delete(_client, name: str, _logger, timeout_s: float):
        deleted.append(name)
        return name != "fail-1"

    monkeypatch.setattr(analyze_media, "safe_delete_file", _safe_delete)

    pending, recovered = analyze_media._retry_cleanup_queue(
        cleanup_queue_path=queue,
        offline=False,
        get_client=lambda: object(),
        logger=logging.getLogger("test"),
        timeout_s=1.0,
        run_id="run-e",
    )

    assert pending == 2
    assert recovered == 1
    assert deleted == ["ok-1", "fail-1"]
    assert '"fail-1"' in queue.read_text(encoding="utf-8")


def test_retry_cleanup_queue_exception_is_swallowed(tmp_path: Path):
    queue_dir = tmp_path / "cleanup_uploads.jsonl"
    queue_dir.mkdir()

    pending, recovered = analyze_media._retry_cleanup_queue(
        cleanup_queue_path=queue_dir,
        offline=False,
        get_client=lambda: object(),
        logger=logging.getLogger("test"),
        timeout_s=1.0,
        run_id="run-e",
    )

    assert pending == 0
    assert recovered == 0


def test_sanitize_ai_and_coerce_confidence_invalid_types():
    cleaned, warnings = analyze_media.sanitize_ai(
        {
            "kind": "截图",
            "category": "其他",
            "title": "测试",
            "tags": [],
            "confidence": {"v": 1},
            "notes": "",
        },
        ["工作", "其他"],
    )

    assert cleaned["confidence"] == 0.0
    assert any("Invalid confidence type: non-numeric value" in w for w in warnings)

    warning_bucket: list[str] = []
    assert (
        analyze_media._coerce_confidence(
            True,
            field_name="merged_transcript_confidence",
            warnings=warning_bucket,
            default_value=0.0,
        )
        == 0.0
    )
    assert (
        analyze_media._coerce_confidence(
            " ",
            field_name="merged_transcript_confidence",
            warnings=warning_bucket,
            default_value=0.0,
        )
        == 0.0
    )
    assert (
        analyze_media._coerce_confidence(
            "abc",
            field_name="merged_transcript_confidence",
            warnings=warning_bucket,
            default_value=0.0,
        )
        == 0.0
    )
    assert (
        analyze_media._coerce_confidence(
            {"x": 1},
            field_name="merged_transcript_confidence",
            warnings=warning_bucket,
            default_value=0.0,
        )
        == 0.0
    )

    assert any("bool" in msg for msg in warning_bucket)
    assert any("Missing" in msg for msg in warning_bucket)
    assert any("non-numeric string" in msg for msg in warning_bucket)
    assert any("non-numeric value" in msg for msg in warning_bucket)
