import csv
import json
from pathlib import Path

import pytest

from packages.infrastructure import manifest_store
from packages.infrastructure.manifest_store import read_jsonl_list, write_csv, write_jsonl, write_jsonl_line


def _sample_row(path: Path):
    return {
        "path": str(path),
        "input_root": str(path.parent),
        "sha1": "abcd" * 10,
        "hash8": "abcdabcd",
        "file_mtime": "2025-01-01T12:00:00",
        "media_type": "image",
        "ai": {
            "kind": "截图",
            "category": "工作",
            "title": "测试",
            "tags": ["标签"],
            "confidence": 0.9,
            "notes": "备注",
        },
        "error": "",
    }


def test_write_and_read_jsonl(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    row = _sample_row(tmp_path / "a.png")
    write_jsonl(manifest, [row])
    rows = read_jsonl_list(manifest, validate=True)
    assert len(rows) == 1
    assert rows[0]["path"].endswith("a.png")


def test_write_jsonl_line(tmp_path: Path):
    out = tmp_path / "out.jsonl"
    row = _sample_row(tmp_path / "b.png")
    with out.open("w", encoding="utf-8") as fh:
        write_jsonl_line(fh, row, fsync=False)
    data = out.read_text(encoding="utf-8").strip()
    assert json.loads(data)["path"].endswith("b.png")


def test_write_csv(tmp_path: Path):
    out = tmp_path / "out.csv"
    row = _sample_row(tmp_path / "c.png")
    write_csv(out, [row])
    with out.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["ai_kind"] == "截图"


def test_write_csv_cleanup_on_error(monkeypatch, tmp_path: Path):
    out = tmp_path / "bad.csv"
    row = _sample_row(tmp_path / "d.png")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("write")

    monkeypatch.setattr(manifest_store, "_write_csv_rows", _boom)

    with pytest.raises(RuntimeError):
        write_csv(out, [row])

    assert not Path(str(out) + ".partial").exists()
