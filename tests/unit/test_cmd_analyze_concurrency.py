import argparse
import json
import threading
import time
from pathlib import Path

from packages.application import analyze_media


def test_cmd_analyze_offline_concurrent(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(b"x")
    (input_dir / "b.png").write_bytes(b"y")

    manifest = tmp_path / "manifest.jsonl"
    args = argparse.Namespace(
        input=str(input_dir),
        manifest=str(manifest),
        csv="",
        model="",
        categories=[],
        fsync_interval=0,
        durability="none",
        inline_max_mb=15.0,
        resize_max_side=0,
        max_retries=0,
        retry_base_s=1.0,
        retry_max_s=10.0,
        audio_segment_threshold=600.0,
        audio_segment_seconds=30.0,
        audio_segment_count=3,
        audio_transcript_max_chars=4000,
        doc_text_max_chars=6000,
        sleep=0.0,
        api_key="",
        offline=True,
        log_level="INFO",
        log_json=False,
        run_id="test_run_0002",
        generator_version="4.0.0",
        max_file_mb=1024.0,
        workers=2,
    )

    analyze_media.cmd_analyze(args)
    assert manifest.exists()
    lines = manifest.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    assert {row["media_type"] for row in rows} == {"image"}
    assert all((row.get("ai") or {}).get("notes") == "offline" for row in rows)


def test_cmd_analyze_workers_use_real_parallelism(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for i in range(6):
        (input_dir / f"{i}.png").write_bytes(b"x")

    manifest = tmp_path / "manifest.jsonl"
    seen_threads = set()
    state = {"running": 0, "peak": 0}
    lock = threading.Lock()

    def fake_analyze_one(path, ctx, get_client):
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
            seen_threads.add(threading.get_ident())
        time.sleep(0.03)
        with lock:
            state["running"] -= 1
        return {
            "path": str(path),
            "media_type": "image",
            "error": "",
            "ai": {"kind": "截图", "category": "工作", "title": path.stem, "tags": []},
        }

    monkeypatch.setattr(analyze_media, "_analyze_one", fake_analyze_one)

    args = argparse.Namespace(
        input=str(input_dir),
        manifest=str(manifest),
        csv="",
        model="",
        categories=[],
        fsync_interval=0,
        durability="none",
        inline_max_mb=15.0,
        resize_max_side=0,
        max_retries=0,
        retry_base_s=1.0,
        retry_max_s=10.0,
        audio_segment_threshold=600.0,
        audio_segment_seconds=30.0,
        audio_segment_count=3,
        audio_transcript_max_chars=4000,
        doc_text_max_chars=6000,
        sleep=0.0,
        api_key="",
        offline=True,
        log_level="INFO",
        log_json=False,
        run_id="test_run_concurrency_real",
        generator_version="4.0.0",
        max_file_mb=1024.0,
        workers=3,
    )

    analyze_media.cmd_analyze(args)
    assert state["peak"] >= 2
    assert len(seen_threads) >= 2


def test_cmd_analyze_tail_batch_fsync(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"

    fsync_calls = []
    original_fsync = analyze_media.os.fsync

    def capture_fsync(fd):
        fsync_calls.append(fd)
        return original_fsync(fd)

    monkeypatch.setattr(analyze_media.os, "fsync", capture_fsync)

    args = argparse.Namespace(
        input=str(input_dir),
        manifest=str(manifest),
        csv="",
        model="",
        categories=[],
        fsync_interval=2,
        durability="none",
        inline_max_mb=15.0,
        resize_max_side=0,
        max_retries=0,
        retry_base_s=1.0,
        retry_max_s=10.0,
        audio_segment_threshold=600.0,
        audio_segment_seconds=30.0,
        audio_segment_count=3,
        audio_transcript_max_chars=4000,
        doc_text_max_chars=6000,
        sleep=0.0,
        api_key="",
        offline=True,
        log_level="INFO",
        log_json=False,
        run_id="test_run_tail_fsync",
        generator_version="4.0.0",
        max_file_mb=1024.0,
        workers=1,
    )

    analyze_media.cmd_analyze(args)
    assert len(fsync_calls) == 1
