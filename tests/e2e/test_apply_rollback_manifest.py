import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def test_apply_generates_rollback_manifest(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    entry = repo_root / "apps" / "cli" / "fileorganize.py"

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    src = input_dir / "sample.png"
    payload = b"rollback"
    src.write_bytes(payload)

    sha1 = hashlib.sha1(payload).hexdigest()
    row = {
        "path": str(src),
        "input_root": str(input_dir),
        "sha1": sha1,
        "hash8": sha1[:8],
        "file_mtime": "2025-01-01T12:00:00",
        "media_type": "image",
        "ai": {
            "kind": "截图",
            "category": "工作",
            "title": "测试",
            "tags": [],
            "confidence": 0.9,
            "notes": "",
        },
        "error": "",
    }

    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    rollback_manifest = tmp_path / "rollback.jsonl"

    apply_cmd = [
        sys.executable,
        str(entry),
        "apply",
        "--manifest",
        str(manifest),
        "--output",
        str(output_dir),
        "--input-root",
        str(input_dir),
        "--verify-sha1",
        "--rollback-manifest",
        str(rollback_manifest),
    ]
    env = os.environ.copy()
    env["FILEORGANIZE_ROLLBACK_HMAC_KEY"] = "e2e-test-rollback-key"
    subprocess.run(apply_cmd, check=True, cwd=str(repo_root), env=env)

    assert not src.exists()
    assert rollback_manifest.exists()
    rollback_rows = [json.loads(line) for line in rollback_manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rollback_rows
    assert rollback_rows[0].get("path") == str(src)
    assert rollback_rows[0].get("new_path")

    rollback_cmd = [
        sys.executable,
        str(entry),
        "rollback",
        "--manifest",
        str(rollback_manifest),
        "--allowed-root",
        str(tmp_path),
    ]
    subprocess.run(rollback_cmd, check=True, cwd=str(repo_root), env=env)

    assert src.exists()

    # Second rollback should be a no-op success: strict_integrity validates
    # signature/record shape, while non-executable rows are skipped safely.
    second = subprocess.run(rollback_cmd, check=False, cwd=str(repo_root), env=env, capture_output=True, text=True)
    assert second.returncode == 0
    assert "rollback_skip_missing_source" in (second.stdout + second.stderr)
    assert src.exists()
