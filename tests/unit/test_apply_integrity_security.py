import argparse
import json
from pathlib import Path

import pytest
from packages.application.apply_changes import cmd_apply, cmd_rollback

from packages.domain.core_utils import sha1_file
from packages.infrastructure.manifest_store import read_jsonl_list, write_jsonl


def _manifest_row(src: Path, input_root: Path) -> dict:
    digest = sha1_file(src)
    return {
        "path": str(src),
        "input_root": str(input_root),
        "sha1": digest,
        "hash8": digest[:8],
        "file_mtime": "2025-01-01T12:00:00",
        "media_type": "image",
        "ai": {
            "kind": "截图",
            "category": "工作",
            "title": "完整性测试",
            "tags": [],
            "confidence": 0.9,
            "notes": "",
        },
        "error": "",
    }


def _apply_once(manifest: Path, input_root: Path, output_root: Path) -> None:
    cmd_apply(
        argparse.Namespace(
            manifest=str(manifest),
            output=str(output_root),
            categories=["工作", "其他"],
            dry_run=False,
            out_manifest="",
            dedupe=True,
            input_root=str(input_root),
            verify_sha1=True,
            fsync_interval=0,
            log_level="INFO",
            log_json=False,
            run_id="apply_run_001",
            generator_version="",
            report="",
            rollback_manifest="",
            crash_inject="",
            resume=True,
            retry_errors=False,
            trust_manifest_input_root=False,
            manifest_input_root_allowlist="",
            chunk_size=10,
            durability="none",
        )
    )


def test_rollback_strict_integrity_allows_signed_row(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FILEORGANIZE_ROLLBACK_HMAC_KEY", "unit-test-rollback-key")
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    src = input_root / "ok.png"
    src.write_bytes(b"ok")

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_manifest_row(src, input_root)])
    _apply_once(manifest, input_root, output_root)

    rows = read_jsonl_list(manifest, validate=True)
    assert rows and rows[0].get("rollback_sig")
    moved = Path(rows[0]["new_path"])
    assert moved.exists()

    cmd_rollback(
        argparse.Namespace(
            manifest=str(manifest),
            dry_run=False,
            overwrite=False,
            allowed_root=str(tmp_path),
            strict_integrity=True,
            log_level="INFO",
            log_json=False,
            run_id="rollback_run_001",
        )
    )

    assert src.exists()
    assert not moved.exists()


def test_rollback_strict_integrity_rejects_tampered_signature(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FILEORGANIZE_ROLLBACK_HMAC_KEY", "unit-test-rollback-key")
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    src = input_root / "bad.png"
    src.write_bytes(b"bad")

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_manifest_row(src, input_root)])
    _apply_once(manifest, input_root, output_root)

    rows = read_jsonl_list(manifest, validate=True)
    moved = Path(rows[0]["new_path"])
    rows[0]["rollback_sig"] = "deadbeef"
    manifest.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="strict_integrity validation failed: rollback candidates exist but all are invalid"):
        cmd_rollback(
            argparse.Namespace(
                manifest=str(manifest),
                dry_run=False,
                overwrite=False,
                allowed_root=str(tmp_path),
                strict_integrity=True,
                log_level="INFO",
                log_json=False,
                run_id="rollback_run_002",
            )
        )

    assert moved.exists()
    assert not src.exists()


def test_rollback_strict_integrity_allows_non_executable_signed_candidate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FILEORGANIZE_ROLLBACK_HMAC_KEY", "unit-test-rollback-key")
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    src = input_root / "missing-source.png"
    src.write_bytes(b"ok")

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_manifest_row(src, input_root)])
    _apply_once(manifest, input_root, output_root)

    rows = read_jsonl_list(manifest, validate=True)
    moved = Path(rows[0]["new_path"])
    moved.unlink()

    cmd_rollback(
        argparse.Namespace(
            manifest=str(manifest),
            dry_run=False,
            overwrite=False,
            allowed_root=str(tmp_path),
            strict_integrity=True,
            log_level="INFO",
            log_json=False,
            run_id="rollback_run_002b",
        )
    )

    assert not moved.exists()
    assert not src.exists()


def test_rollback_strict_integrity_requires_hmac_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FILEORGANIZE_ROLLBACK_HMAC_KEY", raising=False)

    moved = tmp_path / "moved.txt"
    origin = tmp_path / "origin.txt"
    moved.write_text("payload", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "path": str(origin),
                "new_path": str(moved),
                "media_type": "image",
                "run_id": "apply_20260225_000000_deadbeef",
                "rollback_sig": "deadbeef",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="strict_integrity=true requires FILEORGANIZE_ROLLBACK_HMAC_KEY"):
        cmd_rollback(
            argparse.Namespace(
                manifest=str(manifest),
                dry_run=False,
                overwrite=False,
                allowed_root=str(tmp_path),
                strict_integrity=True,
                log_level="INFO",
                log_json=False,
                run_id="rollback_run_003",
            )
        )
