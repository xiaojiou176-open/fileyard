import json
import sys
from pathlib import Path

from apps.cli import cli_app


def test_offline_analyze_then_apply_minimal_flow(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    image_path = input_dir / "截图_集成测试.png"
    ignored_text = input_dir / "ignore.txt"
    image_path.write_bytes(b"not-a-real-png-but-offline-flow-can-handle")
    ignored_text.write_text("not media", encoding="utf-8")

    manifest_path = tmp_path / "manifest.jsonl"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileorganize",
            "analyze",
            "--input",
            str(input_dir),
            "--manifest",
            str(manifest_path),
            "--offline",
            "--workers",
            "1",
            "--durability",
            "none",
        ],
    )
    cli_app.main()

    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["path"] == str(image_path)
    assert rows[0]["ai"]["notes"] == "offline"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileorganize",
            "apply",
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_dir),
            "--input-root",
            str(input_dir),
            "--durability",
            "none",
            "--verify-sha1",
        ],
    )
    cli_app.main()

    updated_rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(updated_rows) == 1
    new_path = updated_rows[0].get("new_path")
    assert new_path
    assert Path(new_path).exists()
    assert not image_path.exists()
    assert ignored_text.exists()


def test_apply_respects_manifest_new_path_override(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    image_path = input_dir / "Screenshot.png"
    image_path.write_bytes(b"offline")
    manifest_path = tmp_path / "manifest.jsonl"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileorganize",
            "analyze",
            "--input",
            str(input_dir),
            "--manifest",
            str(manifest_path),
            "--offline",
            "--workers",
            "1",
            "--durability",
            "none",
        ],
    )
    cli_app.main()

    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    custom_target = output_dir / "custom" / "exact-target.png"
    rows[0]["new_path"] = str(custom_target)
    manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileorganize",
            "apply",
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_dir),
            "--input-root",
            str(input_dir),
            "--durability",
            "none",
            "--verify-sha1",
        ],
    )
    cli_app.main()

    updated_rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert updated_rows[0]["new_path"] == str(custom_target)
    assert custom_target.exists()
    assert not image_path.exists()
