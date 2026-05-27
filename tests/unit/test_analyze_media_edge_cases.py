import argparse
from pathlib import Path

import pytest

from packages.application import analyze_media
from packages.infrastructure.manifest_store import read_jsonl_list


def _base_args(input_dir: Path, manifest: Path):
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
        audio_segment_count=1,
        audio_transcript_max_chars=4000,
        doc_text_max_chars=6000,
        sleep=0.0,
        api_key="fake",
        fsync_interval=0,
        max_files=0,
        max_total_mb=0.0,
    )


def test_cmd_analyze_missing_file_in_iteration(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    ghost = input_dir / "ghost.png"

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "count_media_files", lambda root: 1)
    monkeypatch.setattr(analyze_media, "iter_media_files", lambda root: iter([ghost]))

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert len(rows) == 1
    assert "源文件在处理过程中消失" in (rows[0].get("error") or "")
    assert rows[0].get("path") == str(ghost)
    assert rows[0].get("media_type") == ""


def test_cmd_analyze_build_base_row_error(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    img = input_dir / "a.png"
    img.write_bytes(b"img")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "build_base_row", lambda path: (_ for _ in ()).throw(RuntimeError("boom")))

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert "哈希/属性错误" in (rows[0].get("error") or "")
    assert rows[0].get("path") == str(img)
    assert rows[0].get("media_type") == ""


def test_cmd_analyze_file_too_large_keeps_contract_fields(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    img = input_dir / "big.png"
    img.write_bytes(b"1234567890")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)
    args.max_file_mb = 0.000001

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert len(rows) == 1
    assert "文件超过上限" in (rows[0].get("error") or "")
    assert rows[0].get("path") == str(img)
    assert rows[0].get("media_type") == ""


def test_cmd_analyze_audio_prepare_error(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    audio = input_dir / "a.wav"
    audio.write_bytes(b"audio")

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "extract_audio_fields", lambda *a, **k: {"duration_s": 1.0})
    monkeypatch.setattr(
        analyze_media,
        "prepare_audio_part",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("prep")),
    )

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert "Audio preparation error" in (rows[0].get("error") or "")


def test_cmd_analyze_audio_transcribe_error(monkeypatch, tmp_path: Path):
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
        lambda **k: (_ for _ in ()).throw(RuntimeError("x")),
    )

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert "Transcription error" in (rows[0].get("error") or "")


def test_cmd_analyze_audio_classify_error(monkeypatch, tmp_path: Path):
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
        lambda **k: (_ for _ in ()).throw(RuntimeError("ai")),
    )

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)

    analyze_media.cmd_analyze(args)
    rows = read_jsonl_list(manifest, validate=True)
    assert "AI error" in (rows[0].get("error") or "")


def test_cmd_analyze_partial_cleanup(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    img = input_dir / "a.png"
    img.write_bytes(b"img")

    def _raise(*_args, **_kwargs):
        raise RuntimeError("write")

    monkeypatch.setattr(analyze_media, "write_jsonl_line", _raise)

    manifest = tmp_path / "manifest.jsonl"
    args = _base_args(input_dir, manifest)
    args.offline = True
    args.log_level = "INFO"
    args.log_json = False
    args.run_id = "test_run"
    args.generator_version = "4.0.0"
    args.max_file_mb = 1024.0
    args.workers = 1

    with pytest.raises(SystemExit):
        analyze_media.cmd_analyze(args)

    assert not Path(str(manifest) + ".partial").exists()
