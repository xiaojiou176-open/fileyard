# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
import re
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, TextIO

from packages.domain.pipeline_config import (
    AI_CATEGORY,
    AI_CONFIDENCE,
    AI_KIND,
    AI_NOTES,
    AI_TAGS,
    AI_TITLE,
    APP_VERSION,
    DEFAULT_CHUNK_SIZE,
    KEY_AI,
    KEY_GENERATOR_VERSION,
    KEY_RUN_ID,
    KEY_SCHEMA_VERSION,
    KEY_STATUS,
    MANIFEST_SCHEMA_VERSION,
    MAX_CHUNK_SIZE,
    RowStatus,
)

_SCHEMA_CACHE: Optional[Dict[str, Any]] = None
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


def _fsync_dir(path: Path) -> None:
    dir_fd: int | None = None
    try:
        dir_fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        if dir_fd is not None:
            with suppress(OSError):
                os.close(dir_fd)


def _atomic_replace(src: Path, dst: Path) -> None:
    src.replace(dst)
    _fsync_dir(dst.parent)


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    try:
        with partial.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        _atomic_replace(partial, path)
    except (OSError, TypeError, ValueError):
        if partial.exists():
            with suppress(OSError):
                partial.unlink()
        raise


def open_jsonl_writer(path: Path) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8")


def write_jsonl_line(fh, row: Dict[str, Any], fsync: bool = False) -> None:
    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if fsync:
        fh.flush()
        os.fsync(fh.fileno())


# -----------------------------
# Manifest metadata helpers
# -----------------------------


def attach_manifest_metadata(
    row: Dict[str, Any],
    *,
    run_id: str,
    generator_version: str = APP_VERSION,
    schema_version: int = MANIFEST_SCHEMA_VERSION,
) -> None:
    if run_id:
        normalized = str(run_id).strip()
        if not _RUN_ID_PATTERN.match(normalized):
            raise ValueError(f"Invalid run_id: {run_id!r}")
        run_id = normalized
    if KEY_SCHEMA_VERSION not in row:
        row[KEY_SCHEMA_VERSION] = schema_version
    if run_id and KEY_RUN_ID not in row:
        row[KEY_RUN_ID] = run_id
    if generator_version and KEY_GENERATOR_VERSION not in row:
        row[KEY_GENERATOR_VERSION] = generator_version
    if KEY_STATUS not in row:
        row[KEY_STATUS] = RowStatus.PENDING.value


def detect_schema_versions(rows: Iterable[Dict[str, Any]]) -> List[int]:
    versions = []
    for row in rows:
        val = row.get(KEY_SCHEMA_VERSION)
        if isinstance(val, int) and not isinstance(val, bool):
            versions.append(val)
        elif isinstance(val, str) and val.isdigit():
            versions.append(int(val))
    return sorted(set(versions))


def _load_schema(*, strict: bool = False) -> Optional[Dict[str, Any]]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parents[3],
    ]
    schema_path = None
    for candidate in candidates:
        if not str(candidate):
            continue
        current = candidate / "contracts" / "runtime" / "manifest.schema.json"
        if current.exists():
            schema_path = current
            break
    if schema_path is None:
        if strict:
            attempted = [str(candidate / "contracts" / "runtime" / "manifest.schema.json") for candidate in candidates]
            raise RuntimeError(f"Manifest schema file not found: {' | '.join(attempted)}")
        _SCHEMA_CACHE = None
        return None
    try:
        _SCHEMA_CACHE = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            raise RuntimeError(f"Manifest schema read failed: {exc}") from exc
        _SCHEMA_CACHE = None
    return _SCHEMA_CACHE


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _validate_against_schema(value: Any, schema: Dict[str, Any], path: str = "$") -> None:
    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_matches_type(value, t) for t in expected):
            raise ValueError(f"{path}: field type mismatch, expected {expected}")
    elif isinstance(expected, str):
        if not _matches_type(value, expected):
            raise ValueError(f"{path}: field type mismatch, expected {expected}")

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        raise ValueError(f"{path}: value is not in enum, got {value!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for req_key in required:
            if req_key not in value:
                raise ValueError(f"{path}.{req_key}: missing required field")

        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key not in value:
                continue
            if isinstance(child_schema, dict):
                _validate_against_schema(value[key], child_schema, f"{path}.{key}")
    elif isinstance(value, list):
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for index, item in enumerate(value):
                _validate_against_schema(item, items_schema, f"{path}[{index}]")


def _validate_row_schema(row: Dict[str, Any], schema: Dict[str, Any]) -> None:
    _validate_against_schema(row, schema, "$")


def read_jsonl(path: Path, validate: bool = True) -> Iterator[Dict[str, Any]]:
    if validate:
        try:
            schema = _load_schema(strict=True)
        except RuntimeError as exc:
            raise ValueError(f"manifest schema unavailable: {exc}") from exc
    else:
        schema = None
    with path.open("r", encoding="utf-8") as fh:
        for idx, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"manifest line {idx} JSON parse failed: {exc}") from exc
            if schema is not None:
                try:
                    _validate_row_schema(row, schema)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"manifest line {idx} schema validation failed: {exc}") from exc
            yield row


def read_jsonl_list(path: Path, validate: bool = True) -> List[Dict[str, Any]]:
    return list(read_jsonl(path, validate=validate))


def iter_jsonl_chunks(
    path: Path,
    *,
    validate: bool = True,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Iterator[List[Dict[str, Any]]]:
    size = int(chunk_size or DEFAULT_CHUNK_SIZE)
    if size <= 0:
        size = 1
    elif size > MAX_CHUNK_SIZE:
        size = MAX_CHUNK_SIZE
    buffer: List[Dict[str, Any]] = []
    for row in read_jsonl(path, validate=validate):
        buffer.append(row)
        if len(buffer) >= size:
            yield buffer
            buffer = []
    if buffer:
        yield buffer


# -----------------------------
# CSV helpers
# -----------------------------


def _flatten_row(row: Dict[str, Any]) -> Dict[str, Any]:
    flat = dict(row)
    ai = flat.pop(KEY_AI, {}) or {}
    flat["ai_kind"] = ai.get(AI_KIND)
    flat["ai_category"] = ai.get(AI_CATEGORY)
    flat["ai_title"] = ai.get(AI_TITLE)
    flat["ai_confidence"] = ai.get(AI_CONFIDENCE)
    flat["ai_tags"] = ",".join(ai.get(AI_TAGS, []) or [])
    flat["ai_notes"] = ai.get(AI_NOTES)
    flat["ai_raw"] = json.dumps(ai, ensure_ascii=False)
    return flat


def _write_csv_rows(path: Path, fieldnames: List[str], rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flat_rows = [_flatten_row(r) for r in rows]
    fieldnames = sorted({k for r in flat_rows for k in r.keys()})
    partial = Path(str(path) + ".partial")
    try:
        _write_csv_rows(partial, fieldnames, flat_rows)
        _atomic_replace(partial, path)
    except Exception:
        if partial.exists():
            with suppress(OSError):
                partial.unlink()
        raise


def write_csv_from_manifest(
    manifest_path: Path,
    out_path: Path,
    *,
    validate: bool = False,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(out_path) + ".partial")
    fieldnames: set[str] = set()
    for chunk in iter_jsonl_chunks(manifest_path, validate=validate, chunk_size=chunk_size):
        for row in chunk:
            fieldnames.update(_flatten_row(row).keys())
    ordered = sorted(fieldnames)
    try:
        with partial.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=ordered)
            writer.writeheader()
            for chunk in iter_jsonl_chunks(manifest_path, validate=validate, chunk_size=chunk_size):
                for row in chunk:
                    writer.writerow(_flatten_row(row))
            fh.flush()
            os.fsync(fh.fileno())
        _atomic_replace(partial, out_path)
    except Exception:
        if partial.exists():
            with suppress(OSError):
                partial.unlink()
        raise
