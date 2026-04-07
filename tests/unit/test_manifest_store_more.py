import json
from pathlib import Path

import pytest

from packages.infrastructure import manifest_store


def test_validate_schema_type_mismatch(tmp_path: Path):
    schema = {
        "properties": {
            "path": {"type": "string"},
            "ai": {
                "type": "object",
                "properties": {
                    "confidence": {"type": "number"},
                },
            },
        }
    }

    row = {"path": 123, "ai": {"confidence": "bad"}}

    with pytest.raises(ValueError):
        manifest_store._validate_row_schema(row, schema)


def test_read_jsonl_invalid_json(tmp_path: Path):
    p = tmp_path / "bad.jsonl"
    p.write_text("{bad}\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        list(manifest_store.read_jsonl(p, validate=False))
    assert "line 1" in str(exc_info.value)


def test_read_jsonl_schema_error_has_line(tmp_path: Path):
    p = tmp_path / "bad_schema.jsonl"
    p.write_text(json.dumps({"path": 123}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        list(manifest_store.read_jsonl(p, validate=True))
    assert "line 1" in str(exc_info.value)


def test_validate_schema_required_field_missing():
    schema = {
        "type": "object",
        "required": ["path", "media_type"],
        "properties": {
            "path": {"type": "string"},
            "media_type": {"type": "string"},
        },
    }
    row = {"path": "a.png"}

    with pytest.raises(ValueError) as exc_info:
        manifest_store._validate_row_schema(row, schema)
    assert "$.media_type" in str(exc_info.value)


def test_validate_schema_enum_mismatch():
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["pending", "applied"]},
        },
    }
    row = {"status": "broken"}

    with pytest.raises(ValueError) as exc_info:
        manifest_store._validate_row_schema(row, schema)
    assert "$.status" in str(exc_info.value)
    assert "enum" in str(exc_info.value)


def test_read_jsonl_fail_closed_when_schema_missing(monkeypatch, tmp_path: Path):
    p = tmp_path / "ok.jsonl"
    p.write_text(json.dumps({"path": "a.png"}) + "\n", encoding="utf-8")

    def fake_load_schema(*, strict: bool = False):
        raise RuntimeError("schema missing")

    monkeypatch.setattr(manifest_store, "_load_schema", fake_load_schema)
    with pytest.raises(ValueError) as exc_info:
        list(manifest_store.read_jsonl(p, validate=True))
    assert "manifest schema unavailable" in str(exc_info.value)
