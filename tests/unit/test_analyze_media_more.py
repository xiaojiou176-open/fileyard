import argparse
from pathlib import Path

import pytest

from packages.application import analyze_media
from packages.infrastructure.manifest_store import read_jsonl_list


def test_cmd_analyze_missing_input_dir(tmp_path: Path):
    args = argparse.Namespace(
        input=str(tmp_path / "missing"),
        manifest=str(tmp_path / "m.jsonl"),
        csv="",
        model="m",
        categories=["工作"],
        inline_max_mb=1.0,
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
        api_key="k",
        fsync_interval=0,
    )
    with pytest.raises(SystemExit):
        analyze_media.cmd_analyze(args)


def test_cmd_analyze_missing_api_key(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    args = argparse.Namespace(
        input=str(input_dir),
        manifest=str(tmp_path / "m.jsonl"),
        csv="",
        model="m",
        categories=["工作"],
        inline_max_mb=1.0,
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
        api_key="",
        fsync_interval=0,
    )
    with pytest.raises(SystemExit):
        analyze_media.cmd_analyze(args)


def test_cmd_analyze_missing_model(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    args = argparse.Namespace(
        input=str(input_dir),
        manifest=str(tmp_path / "m.jsonl"),
        csv="",
        model="",
        categories=["工作"],
        inline_max_mb=1.0,
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
        api_key="k",
        fsync_interval=0,
    )
    with pytest.raises(SystemExit):
        analyze_media.cmd_analyze(args)


def test_cmd_analyze_invalid_model_prefix(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    args = argparse.Namespace(
        input=str(input_dir),
        manifest=str(tmp_path / "m.jsonl"),
        csv="",
        model="gpt-4o-mini",
        categories=["工作"],
        inline_max_mb=1.0,
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
        api_key="k",
        fsync_interval=0,
    )
    with pytest.raises(SystemExit):
        analyze_media.cmd_analyze(args)


def test_image_kind_forced_to_screenshot(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    img = input_dir / "截图_001.png"
    img.write_bytes(b"img")

    dummy_client = object()

    def fake_build_client(api_key: str):
        return dummy_client

    def fake_prepare_image_part(path, client, inline_max_mb, resize_max_side, **kwargs):
        return object(), "image/png", None, None, None

    def fake_extract_exif_fields(path):
        return {}

    def fake_call_gemini_with_retry(client, model, image_part, prompt, max_retries, retry_base_s, retry_max_s, **kwargs):
        return {
            "kind": "文档",
            "category": "工作",
            "title": "测试",
            "tags": [],
            "confidence": 0.5,
            "notes": "",
        }, 0

    monkeypatch.setattr(analyze_media, "build_client", fake_build_client)
    monkeypatch.setattr(analyze_media, "prepare_image_part", fake_prepare_image_part)
    monkeypatch.setattr(analyze_media, "extract_exif_fields", fake_extract_exif_fields)
    monkeypatch.setattr(analyze_media, "call_gemini_with_retry", fake_call_gemini_with_retry)

    manifest = tmp_path / "manifest.jsonl"

    args = argparse.Namespace(
        input=str(input_dir),
        manifest=str(manifest),
        csv="",
        model="gemini-test",
        categories=["工作", "其他"],
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
    assert len(rows) == 1
    assert rows[0]["ai"]["kind"] == "截图"
