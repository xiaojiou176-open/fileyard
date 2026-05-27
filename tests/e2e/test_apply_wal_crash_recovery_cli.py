import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _manifest_row(src: Path, input_root: Path, sha1: str) -> dict:
    return {
        "path": str(src),
        "input_root": str(input_root),
        "sha1": sha1,
        "hash8": sha1[:8],
        "file_mtime": "2025-01-01T12:00:00",
        "media_type": "image",
        "ai": {
            "kind": "截图",
            "category": "工作",
            "title": "WAL恢复测试",
            "tags": [],
            "confidence": 0.9,
            "notes": "",
        },
        "error": "",
    }


def _run_apply(
    repo_root: Path,
    manifest: Path,
    output_dir: Path,
    input_dir: Path,
    crash_point: str = "",
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(repo_root / "apps" / "cli" / "fileorganize.py"),
        "apply",
        "--manifest",
        str(manifest),
        "--output",
        str(output_dir),
        "--input-root",
        str(input_dir),
        "--durability",
        "none",
    ]
    env = os.environ.copy()
    env["FILEORGANIZE_ENABLE_TEST_HOOKS"] = "1"
    if crash_point:
        env["FILEORGANIZE_APPLY_CRASH_AT"] = crash_point
    else:
        env.pop("FILEORGANIZE_APPLY_CRASH_AT", None)
    return subprocess.run(cmd, cwd=str(repo_root), text=True, capture_output=True, env=env)


@pytest.mark.parametrize(
    "crash_point",
    [
        "after_move_before_manifest_commit",
        "after_manifest_before_rollback_commit",
        "after_rollback_before_finalize",
    ],
)
def test_cli_apply_recovers_from_wal_crash_across_process_restart(tmp_path: Path, crash_point: str):
    repo_root = Path(__file__).resolve().parents[2]
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    src = input_dir / "sample.png"
    payload = b"wal-e2e-crash-recovery"
    src.write_bytes(payload)

    sha1 = hashlib.sha1(payload).hexdigest()
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(_manifest_row(src=src, input_root=input_dir, sha1=sha1), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    rollback_manifest = tmp_path / "manifest.jsonl.rollback.jsonl"
    wal_file = tmp_path / "manifest.jsonl.apply.wal.json"

    first = _run_apply(
        repo_root=repo_root,
        manifest=manifest,
        output_dir=output_dir,
        input_dir=input_dir,
        crash_point=crash_point,
    )
    assert first.returncode != 0
    assert crash_point in f"{first.stderr}\n{first.stdout}"
    assert wal_file.exists()
    assert not src.exists()

    second = _run_apply(
        repo_root=repo_root,
        manifest=manifest,
        output_dir=output_dir,
        input_dir=input_dir,
        crash_point="",
    )
    assert second.returncode == 0, second.stderr or second.stdout

    assert not wal_file.exists()
    assert not (tmp_path / "manifest.jsonl.partial").exists()
    assert not (tmp_path / "manifest.jsonl.rollback.jsonl.partial").exists()
    assert rollback_manifest.exists()

    manifest_rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    rollback_rows = [json.loads(line) for line in rollback_manifest.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(manifest_rows) == 1

    manifest_row = manifest_rows[0]
    moved = Path(manifest_row["new_path"])

    assert manifest_row.get("status") == "applied"
    assert moved.exists()
    assert moved.is_file()
    assert str(moved).startswith(str(output_dir))
    assert manifest_row.get("path") == str(src)

    applied_map = {
        row.get("new_path"): row for row in manifest_rows if row.get("status") in {"applied", "duplicate"} and row.get("new_path")
    }
    assert len(rollback_rows) <= len(applied_map)
    for rollback_row in rollback_rows:
        traced = applied_map.get(rollback_row.get("new_path"))
        assert traced is not None
        assert rollback_row.get("path") == traced.get("path")
