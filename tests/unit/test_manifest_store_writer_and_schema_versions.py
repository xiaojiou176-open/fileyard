import json
from pathlib import Path

import pytest

from packages.infrastructure import manifest_store


def _row(path: Path):
    return {
        "path": str(path),
        "input_root": str(path.parent),
        "media_type": "image",
        "sha1": "a" * 40,
        "hash8": "aaaaaaaa",
        "file_mtime": "2026-01-01T00:00:00",
        "ai": {
            "kind": "截图",
            "category": "工作",
            "title": "示例",
            "tags": ["x"],
            "confidence": 0.8,
        },
    }


def test_open_jsonl_writer_creates_parent_and_write_line_fsync(monkeypatch, tmp_path: Path):
    out = tmp_path / "nested" / "manifest.jsonl"
    called = {"fsync": False}

    def fake_fsync(_fd):
        called["fsync"] = True

    monkeypatch.setattr(manifest_store.os, "fsync", fake_fsync)

    with manifest_store.open_jsonl_writer(out) as fh:
        manifest_store.write_jsonl_line(fh, _row(tmp_path / "a.png"), fsync=True)

    assert out.exists()
    assert called["fsync"] is True


def test_detect_schema_versions_ignores_non_digit_values():
    rows = [{"schema_version": 3}, {"schema_version": "4"}, {"schema_version": "4a"}, {"x": 1}]
    assert manifest_store.detect_schema_versions(rows) == [3, 4]


def test_detect_schema_versions_ignores_bool_like_values():
    rows = [{"schema_version": True}, {"schema_version": False}, {"schema_version": 2}]
    # Counterfactual: 若 bool 被当作 int 版本收集，此处会变红。
    assert manifest_store.detect_schema_versions(rows) == [2]


def test_detect_schema_versions_dedupes_and_sorts_mixed_numeric_inputs():
    rows = [{"schema_version": "10"}, {"schema_version": 2}, {"schema_version": "002"}, {"schema_version": 10}]
    assert manifest_store.detect_schema_versions(rows) == [2, 10]


def test_iter_jsonl_chunks_with_non_positive_size(tmp_path: Path):
    manifest = tmp_path / "m.jsonl"
    manifest_store.write_jsonl(manifest, [_row(tmp_path / "1.png"), _row(tmp_path / "2.png")])

    chunks = list(manifest_store.iter_jsonl_chunks(manifest, validate=False, chunk_size=-1))

    assert len(chunks) == 2
    assert all(len(chunk) == 1 for chunk in chunks)


def test_read_jsonl_skips_blank_lines(tmp_path: Path):
    manifest = tmp_path / "m.jsonl"
    manifest.write_text("\n" + json.dumps(_row(tmp_path / "a.png"), ensure_ascii=False) + "\n\n", encoding="utf-8")

    rows = list(manifest_store.read_jsonl(manifest, validate=False))
    assert len(rows) == 1
    assert rows[0]["path"].endswith("a.png")


def test_write_csv_from_manifest_success(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    out = tmp_path / "out.csv"
    manifest_store.write_jsonl(manifest, [_row(tmp_path / "a.png"), _row(tmp_path / "b.png")])

    manifest_store.write_csv_from_manifest(manifest, out, validate=False, chunk_size=1)

    content = out.read_text(encoding="utf-8")
    assert "ai_kind" in content
    assert "a.png" in content
    assert "b.png" in content


def test_write_csv_from_manifest_cleans_partial_on_failure(monkeypatch, tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    out = tmp_path / "bad.csv"
    manifest_store.write_jsonl(manifest, [_row(tmp_path / "a.png")])

    real_open = Path.open
    partial_path = Path(str(out) + ".partial")

    def fake_open(self, *args, **kwargs):
        if self == partial_path:
            real_open(self, *args, **kwargs).close()
            raise OSError("cannot open partial")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fake_open)

    with pytest.raises(OSError):
        manifest_store.write_csv_from_manifest(manifest, out, validate=False)

    assert not partial_path.exists()


def test_attach_manifest_metadata_normalizes_run_id_and_preserves_existing_fields():
    row = {
        "schema_version": 99,
        "run_id": "existing",
        "generator_version": "old",
        "status": "applied",
    }

    manifest_store.attach_manifest_metadata(row, run_id="  run-123  ", generator_version="new", schema_version=1)

    assert row["run_id"] == "existing"
    assert row["schema_version"] == 99
    assert row["generator_version"] == "old"
    assert row["status"] == "applied"


def test_attach_manifest_metadata_rejects_invalid_run_id():
    with pytest.raises(ValueError, match="Invalid run_id"):
        manifest_store.attach_manifest_metadata({}, run_id="bad run id!")


def test_validate_schema_number_rejects_bool_value():
    schema = {"type": "object", "properties": {"confidence": {"type": "number"}}}

    with pytest.raises(ValueError, match="field type mismatch"):
        manifest_store._validate_row_schema({"confidence": True}, schema)


def test_validate_against_schema_nested_array_required_error_path():
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "string"}},
        },
    }

    with pytest.raises(ValueError) as exc_info:
        manifest_store._validate_against_schema([{}], schema, "$")
    # Counterfactual: 若去掉 list 递归或 required 校验，此处会失败。
    assert "$[0].id" in str(exc_info.value)


def test_validate_against_schema_supports_type_union_and_rejects_bool_for_number():
    schema = {"type": ["string", "number"]}
    manifest_store._validate_against_schema("ok", schema, "$")
    manifest_store._validate_against_schema(42, schema, "$")
    with pytest.raises(ValueError, match="field type mismatch"):
        manifest_store._validate_against_schema(True, schema, "$")


def test_flatten_row_handles_missing_ai_payload_with_stable_defaults():
    row = {"path": "/tmp/a.png", "ai": None}
    flat = manifest_store._flatten_row(row)
    assert flat["path"] == "/tmp/a.png"
    assert flat["ai_kind"] is None
    assert flat["ai_category"] is None
    assert flat["ai_title"] is None
    assert flat["ai_confidence"] is None
    assert flat["ai_tags"] == ""
    assert flat["ai_notes"] is None
    assert flat["ai_raw"] == "{}"


def test_attach_manifest_metadata_blank_run_id_does_not_inject_run_id():
    row = {}
    manifest_store.attach_manifest_metadata(row, run_id="", generator_version="v1", schema_version=7)

    assert "run_id" not in row
    assert row["schema_version"] == 7
    assert row["generator_version"] == "v1"
    assert row["status"] == "pending"


def test_attach_manifest_metadata_whitespace_run_id_is_rejected():
    with pytest.raises(ValueError, match="Invalid run_id"):
        manifest_store.attach_manifest_metadata({}, run_id="   ")


def test_write_csv_from_manifest_cleans_partial_when_writerow_fails(monkeypatch, tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    out = tmp_path / "fail.csv"
    manifest_store.write_jsonl(manifest, [_row(tmp_path / "a.png")])

    real_writerow = manifest_store.csv.DictWriter.writerow
    state = {"calls": 0}

    def fake_writerow(self, rowdict):
        state["calls"] += 1
        if state["calls"] >= 2:
            raise OSError("writerow failed")
        return real_writerow(self, rowdict)

    monkeypatch.setattr(manifest_store.csv.DictWriter, "writerow", fake_writerow)
    with pytest.raises(OSError, match="writerow failed"):
        manifest_store.write_csv_from_manifest(manifest, out, validate=False, chunk_size=1)
    assert not Path(str(out) + ".partial").exists()


def test_write_csv_from_manifest_empty_input_produces_header_only_csv(tmp_path: Path):
    manifest = tmp_path / "empty.jsonl"
    out = tmp_path / "empty.csv"
    manifest.write_text("", encoding="utf-8")

    manifest_store.write_csv_from_manifest(manifest, out, validate=False, chunk_size=3)

    # Counterfactual: 若 chunk/fieldnames 初始化逻辑被改坏，空输入可能抛异常。
    assert out.read_text(encoding="utf-8") in ("\n", "\r\n")


def test_load_schema_returns_cache_without_filesystem_lookup(monkeypatch):
    cached = {"type": "object", "cached": True}
    monkeypatch.setattr(manifest_store, "_SCHEMA_CACHE", cached)
    monkeypatch.setattr(manifest_store, "__file__", "/tmp/should-not-be-used/manifest_store.py")

    assert manifest_store._load_schema(strict=True) is cached


def test_read_jsonl_validate_uses_strict_schema_loading_and_rejects_invalid_row(monkeypatch, tmp_path: Path):
    manifest = tmp_path / "m.jsonl"
    manifest.write_text(json.dumps({"path": "/tmp/a.png"}) + "\n", encoding="utf-8")
    strict_flags: list[bool] = []
    schema = {
        "type": "object",
        "required": ["path", "media_type"],
        "properties": {"path": {"type": "string"}, "media_type": {"type": "string"}},
    }

    def fake_load_schema(*, strict: bool = False):
        strict_flags.append(strict)
        return schema

    monkeypatch.setattr(manifest_store, "_load_schema", fake_load_schema)

    with pytest.raises(ValueError) as exc_info:
        list(manifest_store.read_jsonl(manifest, validate=True))

    assert strict_flags == [True]
    assert "line 1 schema validation failed" in str(exc_info.value)
    assert "$.media_type" in str(exc_info.value)


def test_validate_against_schema_recursive_nested_enum_error_path():
    schema = {
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"labels": {"type": "array", "items": {"type": "string", "enum": ["ok", "pass"]}}},
                },
            }
        },
    }

    with pytest.raises(ValueError) as exc_info:
        manifest_store._validate_against_schema(
            {"nodes": [{"labels": ["ok", "bad"]}]},
            schema,
            "$",
        )

    assert "$.nodes[0].labels[1]" in str(exc_info.value)
    assert "enum" in str(exc_info.value)


def test_write_csv_from_manifest_forwards_validate_and_chunk_size(monkeypatch, tmp_path: Path):
    manifest = tmp_path / "m.jsonl"
    out = tmp_path / "out.csv"
    manifest.write_text("", encoding="utf-8")
    calls: list[tuple[str, bool, int]] = []
    row = _row(tmp_path / "z.png")

    def fake_iter_jsonl_chunks(path: Path, *, validate: bool = True, chunk_size: int = 1000):
        calls.append((str(path), validate, chunk_size))
        yield [row]

    monkeypatch.setattr(manifest_store, "iter_jsonl_chunks", fake_iter_jsonl_chunks)

    manifest_store.write_csv_from_manifest(manifest, out, validate=True, chunk_size=7)

    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "ai_kind" in content
    assert "z.png" in content
    assert calls == [(str(manifest), True, 7), (str(manifest), True, 7)]
