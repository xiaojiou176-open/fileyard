import argparse
import json
from pathlib import Path

import pytest

from packages.application import apply_changes
from packages.domain.pipeline_config import KEY_ERROR_CODE, ErrorCode
from packages.infrastructure.manifest_store import read_jsonl_list, write_jsonl


def _base_row(src: Path, input_root: Path) -> dict:
    digest = apply_changes.sha1_file(src)
    return {
        "schema_version": 2,
        "path": str(src),
        "input_root": str(input_root),
        "sha1": digest,
        "hash8": digest[:8],
        "file_mtime": "2025-01-01T12:00:00",
        "media_type": "image",
        "ai": {
            "kind": "截图",
            "category": "工作",
            "title": "测试",
            "tags": [],
            "confidence": 1,
            "notes": "",
        },
        "error": "",
    }


def _apply_args(manifest: Path, input_root: Path, output_root: Path, **extra):
    base = dict(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=True,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=False,
        fsync_interval=0,
        durability="none",
        resume=True,
        retry_errors=False,
        log_level="INFO",
        log_json=False,
        run_id="apply_run_c_001",
        generator_version="",
        report="",
        rollback_manifest="",
        trust_manifest_input_root=False,
        manifest_input_root_allowlist="",
    )
    base.update(extra)
    return argparse.Namespace(**base)


def test_helpers_verify_and_resolve_branches(monkeypatch, tmp_path: Path):
    missing_sig = {"run_id": "run-1"}
    assert apply_changes._verify_rollback_record(missing_sig, "run-1") is False

    wrong_run = {"run_id": "run-x", "rollback_sig": "abc"}
    assert apply_changes._verify_rollback_record(wrong_run, "run-y") is False

    invalid_run = {
        "run_id": "!!",
        "path": "a",
        "new_path": "b",
        "media_type": "image",
        "status": "applied",
        "applied_at": "2025-01-01T00:00:00",
        "rollback_sig": "deadbeef",
    }
    assert apply_changes._verify_rollback_record(invalid_run, "!!") is False

    original_resolve = apply_changes.Path.resolve

    def _boom_resolve(self):
        if self.name == "bad":
            raise RuntimeError("resolve fail")
        return original_resolve(self)

    monkeypatch.setattr(apply_changes.Path, "resolve", _boom_resolve)
    assert apply_changes._resolve_if_exists(str(tmp_path / "bad")) is None


def test_cmd_apply_retry_errors_and_resume_outside_root(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    outside_root = tmp_path / "outside"
    input_root.mkdir()
    output_root.mkdir()
    outside_root.mkdir()

    src = input_root / "a.png"
    src.write_bytes(b"x")
    resumed = outside_root / "resumed.png"
    resumed.write_bytes(b"y")

    row = _base_row(src, input_root)
    row["error"] = "old-error"
    row["status_reason"] = "legacy"
    row["new_path"] = str(resumed)
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

    apply_changes.cmd_apply(
        _apply_args(
            manifest,
            input_root,
            output_root,
            retry_errors=True,
            verify_sha1=False,
        )
    )

    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0][KEY_ERROR_CODE] == ErrorCode.INPUT_ROOT_MISMATCH.value
    assert "legacy" not in rows[0].get("status_reason", "")


def test_cmd_apply_manifest_input_root_missing_when_trusted(tmp_path: Path):
    output_root = tmp_path / "output"
    output_root.mkdir()

    src = tmp_path / "orphan.png"
    src.write_bytes(b"x")
    row = {
        "schema_version": 2,
        "path": str(src),
        "sha1": apply_changes.sha1_file(src),
        "hash8": "abcd1234",
        "file_mtime": "2025-01-01T12:00:00",
        "media_type": "image",
        "ai": {
            "kind": "截图",
            "category": "工作",
            "title": "测试",
            "tags": [],
            "confidence": 1,
            "notes": "",
        },
        "error": "",
    }
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [row])

    apply_changes.cmd_apply(
        argparse.Namespace(
            manifest=str(manifest),
            output=str(output_root),
            categories=["工作", "其他"],
            dry_run=True,
            out_manifest="",
            dedupe=True,
            input_root="",
            verify_sha1=False,
            fsync_interval=0,
            durability="none",
            resume=False,
            retry_errors=False,
            log_level="INFO",
            log_json=False,
            run_id="apply_run_c_002",
            generator_version="",
            report="",
            rollback_manifest="",
            trust_manifest_input_root=True,
            manifest_input_root_allowlist=str(tmp_path),
        )
    )

    rows = read_jsonl_list(manifest, validate=True)
    assert rows[0][KEY_ERROR_CODE] == ErrorCode.INPUT_ROOT_INVALID.value


def test_cmd_rollback_strict_integrity_invalid_rows_fail_closed(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FILEYARD_ROLLBACK_HMAC_KEY", "key-c")

    src1 = tmp_path / "moved1.txt"
    src2 = tmp_path / "moved2.txt"
    src1.write_text("a", encoding="utf-8")
    src2.write_text("b", encoding="utf-8")

    dst1 = tmp_path / "orig1.txt"
    dst2 = tmp_path / "orig2.txt"

    rows = [
        {
            "path": str(dst1),
            "new_path": str(src1),
            "media_type": "image",
            "run_id": "apply_20260225_000000_abcd",
            "rollback_sig": "deadbeef",
        },
        {
            "path": str(dst2),
            "new_path": str(src2),
            "media_type": "image",
            "run_id": "another_run_id",
            "rollback_sig": "deadbeef",
        },
    ]
    manifest = tmp_path / "rollback_manifest.jsonl"
    manifest.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="strict_integrity validation failed: rollback candidates exist but all are invalid"):
        apply_changes.cmd_rollback(
            argparse.Namespace(
                manifest=str(manifest),
                dry_run=False,
                overwrite=False,
                allowed_root=str(tmp_path),
                strict_integrity=True,
                log_level="INFO",
                log_json=False,
                run_id="rollback_run_c_001",
            )
        )

    assert src1.exists()
    assert src2.exists()
    assert not dst1.exists()
    assert not dst2.exists()


def test_cmd_rollback_strict_integrity_valid_signature_with_missing_source_does_not_fail_closed(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("FILEYARD_ROLLBACK_HMAC_KEY", "key-c")
    run_id = "apply_20260225_000000_abcd"
    src_missing = tmp_path / "missing.txt"
    dst = tmp_path / "orig.txt"

    row = {
        "path": str(dst),
        "new_path": str(src_missing),
        "media_type": "image",
        "status": "applied",
        "applied_at": "2026-02-25T00:00:00",
        "run_id": run_id,
    }
    row["rollback_sig"] = apply_changes._sign_rollback_record(row, run_id)

    manifest = tmp_path / "rollback_manifest_valid_missing_src.jsonl"
    manifest.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    apply_changes.cmd_rollback(
        argparse.Namespace(
            manifest=str(manifest),
            dry_run=False,
            overwrite=False,
            allowed_root=str(tmp_path),
            strict_integrity=True,
            log_level="INFO",
            log_json=False,
            run_id="rollback_run_c_002",
        )
    )

    assert not src_missing.exists()
    assert not dst.exists()
