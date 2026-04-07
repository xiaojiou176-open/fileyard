import argparse
from pathlib import Path

from packages.application import analyze_media
from packages.infrastructure.manifest_store import read_jsonl_list


def test_pdf_ai_error_triggers_cleanup(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    pdf = input_dir / "a.pdf"
    pdf.write_bytes(b"pdf")

    deleted = []

    monkeypatch.setattr(analyze_media, "build_client", lambda api_key: object())
    monkeypatch.setattr(analyze_media, "build_file_part", lambda *a, **k: (object(), "application/pdf", "files/99"))
    monkeypatch.setattr(
        analyze_media,
        "call_gemini_with_retry",
        lambda **k: (_ for _ in ()).throw(RuntimeError("ai")),
    )

    def _fake_safe_delete_file(client, name, logger=None, **kwargs):
        deleted.append(name)
        return True

    monkeypatch.setattr(analyze_media, "safe_delete_file", _fake_safe_delete_file)

    manifest = tmp_path / "manifest.jsonl"
    args = argparse.Namespace(
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
    )

    analyze_media.cmd_analyze(args)

    rows = read_jsonl_list(manifest, validate=True)
    assert "AI error" in (rows[0].get("error") or "")
    assert "files/99" in deleted
