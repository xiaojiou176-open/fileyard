import json
import sys
from pathlib import Path

from apps.cli import cli_app


def test_analyze_online_nonempty_records_ai_fields_and_status(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    image = input_dir / "a.png"
    image.write_bytes(b"img")
    manifest = tmp_path / "manifest.jsonl"

    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3-flash-preview")
    monkeypatch.setattr("packages.application.analyze_media.build_client", lambda api_key: object())
    monkeypatch.setattr(
        "packages.application.analyze_media.call_gemini_with_retry",
        lambda **kwargs: (
            {
                "kind": "截图",
                "category": "工作",
                "title": "测试",
                "tags": ["标签"],
                "confidence": 0.9,
                "notes": "",
            },
            0,
        ),
    )
    monkeypatch.setattr(
        "packages.application.analyze_media.prepare_image_part",
        lambda path, client, inline_max_mb, resize_max_side, **kwargs: (object(), "image/png", None, None, None),
    )
    monkeypatch.setattr("packages.application.analyze_media.extract_exif_fields", lambda path: {})

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileman",
            "analyze",
            "--input",
            str(input_dir),
            "--manifest",
            str(manifest),
            "--workers",
            "1",
        ],
    )
    cli_app.main()

    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row.get("error") == ""
    assert row.get("status") == "pending"
    assert row.get("ai", {}).get("kind") == "截图"
