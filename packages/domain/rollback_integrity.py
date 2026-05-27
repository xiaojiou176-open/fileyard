# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from typing import Any, Dict, Iterable, List

from packages.domain.pipeline_config import (
    KEY_APPLIED_AT,
    KEY_MEDIA_TYPE,
    KEY_NEW_PATH,
    KEY_PATH,
    KEY_SCHEMA_VERSION,
    KEY_STATUS,
    MANIFEST_SCHEMA_VERSION,
    RowStatus,
)

ROLLBACK_SIG_KEY = "rollback_sig"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


def _normalize_run_id(value: str) -> str:
    run_id = str(value or "").strip()
    if not run_id or not RUN_ID_PATTERN.match(run_id):
        raise ValueError(f"Invalid run_id: {run_id!r}")
    return run_id


def _build_rollback_from_manifest(manifest_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rebuilt: List[Dict[str, Any]] = []
    for row in manifest_rows:
        status = str(row.get(KEY_STATUS, "") or "")
        if status not in {RowStatus.APPLIED.value, RowStatus.DUPLICATE.value}:
            continue
        src = str(row.get(KEY_PATH, "") or "")
        new_path = str(row.get(KEY_NEW_PATH, "") or "")
        if not src or not new_path:
            continue
        rebuilt.append(
            {
                KEY_PATH: src,
                KEY_NEW_PATH: new_path,
                KEY_MEDIA_TYPE: str(row.get(KEY_MEDIA_TYPE, "") or ""),
                KEY_STATUS: status,
                KEY_APPLIED_AT: str(row.get(KEY_APPLIED_AT, "") or ""),
                KEY_SCHEMA_VERSION: row.get(KEY_SCHEMA_VERSION, MANIFEST_SCHEMA_VERSION),
            }
        )
    return rebuilt


def _rollback_signing_key(run_id: str) -> bytes:
    secret = str(os.environ.get("FILEYARD_ROLLBACK_HMAC_KEY", "") or "").strip()
    if secret:
        return secret.encode("utf-8")
    # Without a dedicated secret, bind the signature to run_id to block cross-run replay.
    return run_id.encode("utf-8")


def _has_strong_rollback_signing_key() -> bool:
    return bool(str(os.environ.get("FILEYARD_ROLLBACK_HMAC_KEY", "") or "").strip())


def _rollback_signature_payload(row: Dict[str, Any], run_id: str) -> str:
    payload = {
        "run_id": run_id,
        KEY_PATH: str(row.get(KEY_PATH, "") or ""),
        KEY_NEW_PATH: str(row.get(KEY_NEW_PATH, "") or ""),
        KEY_MEDIA_TYPE: str(row.get(KEY_MEDIA_TYPE, "") or ""),
        KEY_STATUS: str(row.get(KEY_STATUS, "") or ""),
        KEY_APPLIED_AT: str(row.get(KEY_APPLIED_AT, "") or ""),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sign_rollback_record(row: Dict[str, Any], run_id: str) -> str:
    canonical_run_id = _normalize_run_id(run_id)
    payload = _rollback_signature_payload(row, canonical_run_id).encode("utf-8")
    return hmac.new(_rollback_signing_key(canonical_run_id), payload, hashlib.sha256).hexdigest()


def _verify_rollback_record(row: Dict[str, Any], expected_run_id: str) -> bool:
    provided = str(row.get(ROLLBACK_SIG_KEY, "") or "").strip().lower()
    if not provided:
        return False
    row_run_id = str(row.get("run_id", "") or "")
    if row_run_id != expected_run_id:
        return False
    try:
        expected = _sign_rollback_record(row, expected_run_id)
    except ValueError:
        return False
    return hmac.compare_digest(expected, provided)
