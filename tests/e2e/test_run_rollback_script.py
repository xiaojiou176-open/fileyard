import json
import os
import subprocess
from pathlib import Path

from packages.application.apply_changes import _sign_rollback_record


def _signed_row(path: Path, new_path: Path, run_id: str, hmac_key: str) -> dict[str, str]:
    row: dict[str, str] = {
        "path": str(path),
        "new_path": str(new_path),
        "media_type": "image",
        "run_id": run_id,
    }
    old = os.environ.get("FILEYARD_ROLLBACK_HMAC_KEY")
    os.environ["FILEYARD_ROLLBACK_HMAC_KEY"] = hmac_key
    try:
        row["rollback_sig"] = _sign_rollback_record(row, run_id)
    finally:
        if old is None:
            os.environ.pop("FILEYARD_ROLLBACK_HMAC_KEY", None)
        else:
            os.environ["FILEYARD_ROLLBACK_HMAC_KEY"] = old
    return row


def test_run_rollback_script_moves_back(tmp_path: Path):
    script_root = Path(__file__).resolve().parents[2]
    run_rollback = script_root / "tooling" / "runtime" / "run_rollback.sh"

    original = tmp_path / "orig.txt"
    moved = tmp_path / "moved.txt"
    original.write_text("old", encoding="utf-8")
    moved.write_text("new", encoding="utf-8")

    hmac_key = "e2e-test-rollback-key"
    row = _signed_row(original, moved, "apply_20260225_000000_deadbeef", hmac_key)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")

    cmd = [
        str(run_rollback),
        "--manifest",
        str(manifest),
        "--allowed-root",
        str(tmp_path),
        "--overwrite",
    ]
    env = os.environ.copy()
    env["FILEYARD_ROLLBACK_HMAC_KEY"] = hmac_key
    env["FILEYARD_ALLOW_HOST_EXECUTION"] = "1"
    subprocess.run(
        cmd,
        check=True,
        cwd=str(script_root),
        env=env,
        capture_output=True,
        text=True,
    )

    assert original.read_text(encoding="utf-8") == "new"
    assert not moved.exists()


def test_run_rollback_script_overwrite_dry_run_keeps_files(tmp_path: Path):
    script_root = Path(__file__).resolve().parents[2]
    run_rollback = script_root / "tooling" / "runtime" / "run_rollback.sh"

    original = tmp_path / "orig.txt"
    moved = tmp_path / "moved.txt"
    original.write_text("old", encoding="utf-8")
    moved.write_text("new", encoding="utf-8")

    hmac_key = "e2e-test-rollback-key"
    row = _signed_row(original, moved, "apply_20260225_000000_deadbeef", hmac_key)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")

    cmd = [
        str(run_rollback),
        "--manifest",
        str(manifest),
        "--allowed-root",
        str(tmp_path),
        "--overwrite",
        "--dry-run",
    ]
    env = os.environ.copy()
    env["FILEYARD_ROLLBACK_HMAC_KEY"] = hmac_key
    env["FILEYARD_ALLOW_HOST_EXECUTION"] = "1"
    subprocess.run(cmd, check=True, cwd=str(script_root), env=env)

    assert original.read_text(encoding="utf-8") == "old"
    assert moved.read_text(encoding="utf-8") == "new"


def test_run_rollback_script_outside_allowed_root_does_not_block_valid_row(tmp_path: Path):
    script_root = Path(__file__).resolve().parents[2]
    run_rollback = script_root / "tooling" / "runtime" / "run_rollback.sh"

    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    inside_src = allowed_root / "inside-moved.txt"
    inside_src.write_text("inside", encoding="utf-8")
    inside_dst = allowed_root / "inside-orig.txt"

    outside_src = tmp_path / "outside-moved.txt"
    outside_src.write_text("outside", encoding="utf-8")
    outside_dst = tmp_path / "outside-orig.txt"

    run_id = "apply_20260225_000000_deadbeef"
    hmac_key = "e2e-test-rollback-key"
    rows = [
        _signed_row(outside_dst, outside_src, run_id, hmac_key),
        _signed_row(inside_dst, inside_src, run_id, hmac_key),
    ]
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    cmd = [
        str(run_rollback),
        "--manifest",
        str(manifest),
        "--allowed-root",
        str(allowed_root),
    ]
    env = os.environ.copy()
    env["FILEYARD_ROLLBACK_HMAC_KEY"] = hmac_key
    env["FILEYARD_ALLOW_HOST_EXECUTION"] = "1"
    proc = subprocess.run(
        cmd,
        check=True,
        cwd=str(script_root),
        env=env,
        capture_output=True,
        text=True,
    )

    assert outside_src.exists()
    assert not outside_dst.exists()
    assert not inside_src.exists()
    assert inside_dst.read_text(encoding="utf-8") == "inside"
    assert "outside allowed_root" in (proc.stdout + proc.stderr)
