import argparse
from pathlib import Path

from packages.application import analyze_media
from packages.infrastructure.manifest_store import read_jsonl_list


def test_cmd_analyze_audio_with_segments(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    audio = input_dir / "a.wav"
    audio.write_bytes(b"audio")

    seg_dir = tmp_path / "segs"
    seg_dir.mkdir()
    seg1 = seg_dir / "seg1.wav"
    seg2 = seg_dir / "seg2.wav"
    seg1.write_bytes(b"s1")
    seg2.write_bytes(b"s2")

    deleted = []

    def fake_build_client(api_key: str):
        return object()

    def fake_extract_audio_fields(path):
        return {
            "duration_s": 1000.0,
            "sample_rate": 16000,
            "channels": 1,
            "bitrate_kbps": 64,
        }

    def fake_extract_audio_segments(path, plan, **kwargs):
        return [(seg1, 0.0, 10.0), (seg2, 10.0, 10.0)], seg_dir

    def fake_prepare_audio_part(path, client, inline_max_mb, **kwargs):
        return object(), "audio/wav", f"files/{path.name}"

    def fake_call_gemini_with_retry(**kwargs):
        return {"transcript": "你好", "language": "中文", "confidence": 0.9, "notes": ""}, 1

    def fake_call_gemini_text_with_retry(**kwargs):
        return {
            "kind": "音频",
            "category": "工作",
            "title": "测试音频",
            "tags": ["标签"],
            "confidence": 0.8,
            "notes": "",
        }, 0

    def fake_safe_delete_file(client, name, logger=None, **kwargs):
        deleted.append(name)
        return True

    monkeypatch.setattr(analyze_media, "build_client", fake_build_client)
    monkeypatch.setattr(analyze_media, "extract_audio_fields", fake_extract_audio_fields)
    monkeypatch.setattr(analyze_media, "extract_audio_segments", fake_extract_audio_segments)
    monkeypatch.setattr(analyze_media, "prepare_audio_part", fake_prepare_audio_part)
    monkeypatch.setattr(analyze_media, "call_gemini_with_retry", fake_call_gemini_with_retry)
    monkeypatch.setattr(analyze_media, "call_gemini_text_with_retry", fake_call_gemini_text_with_retry)
    monkeypatch.setattr(analyze_media, "safe_delete_file", fake_safe_delete_file)

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
        audio_segment_threshold=1.0,
        audio_segment_seconds=10.0,
        audio_segment_count=2,
        audio_transcript_max_chars=4000,
        doc_text_max_chars=6000,
        sleep=0.0,
        api_key="fake",
        fsync_interval=0,
    )

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert len(rows) == 1
    row = rows[0]
    assert row["transcript"]
    assert len(row["transcript_segments"]) == 2
    assert row["ai"]["kind"] == "音频"
    assert "files/seg1.wav" in deleted
    assert "files/seg2.wav" in deleted


def test_cmd_analyze_audio_empty_transcript(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    audio = input_dir / "a.wav"
    audio.write_bytes(b"audio")

    def fake_build_client(api_key: str):
        return object()

    def fake_extract_audio_fields(path):
        return {"duration_s": 1.0}

    def fake_prepare_audio_part(path, client, inline_max_mb, **kwargs):
        return object(), "audio/wav", None

    def fake_call_gemini_with_retry(**kwargs):
        return {"transcript": "", "language": "", "confidence": 0.0, "notes": ""}, 0

    monkeypatch.setattr(analyze_media, "build_client", fake_build_client)
    monkeypatch.setattr(analyze_media, "extract_audio_fields", fake_extract_audio_fields)
    monkeypatch.setattr(analyze_media, "prepare_audio_part", fake_prepare_audio_part)
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
    assert rows[0]["ai"]["notes"] == "Transcript empty"
    assert "Transcript empty" in (rows[0].get("ai_warning") or "")
