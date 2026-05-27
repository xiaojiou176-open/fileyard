import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def test_cli_apply_rollback(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fileyard = repo_root / "apps" / "cli" / "fileyard.py"

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    src = input_dir / "sample.png"
    data = b"e2e"
    src.write_bytes(data)

    sha1 = hashlib.sha1(data).hexdigest()
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

    apply_cmd = [
        sys.executable,
        str(fileyard),
        "apply",
        "--manifest",
        str(manifest),
        "--output",
        str(output_dir),
        "--input-root",
        str(input_dir),
        "--verify-sha1",
    ]
    env = os.environ.copy()
    env["FILEYARD_ROLLBACK_HMAC_KEY"] = "e2e-test-rollback-key"
    subprocess.run(apply_cmd, check=True, cwd=str(repo_root), env=env)

    assert not src.exists()

    rollback_cmd = [
        sys.executable,
        str(fileyard),
        "rollback",
        "--manifest",
        str(manifest),
        "--allowed-root",
        str(tmp_path),
    ]
    subprocess.run(rollback_cmd, check=True, cwd=str(repo_root), env=env)

    assert src.exists()
    assert src.read_bytes() == data


def test_cli_analyze_fails_on_manifest_lock_contention(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fileyard = repo_root / "apps" / "cli" / "fileyard.py"

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"

    lock_path = Path(str(manifest) + ".lock")
    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "ts": time.time()}, ensure_ascii=False),
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        str(fileyard),
        "analyze",
        "--input",
        str(input_dir),
        "--manifest",
        str(manifest),
        "--offline",
    ]
    proc = subprocess.run(cmd, check=False, cwd=str(repo_root), capture_output=True, text=True)

    assert proc.returncode != 0
    assert "Failed to acquire task lock" in (proc.stdout + proc.stderr)


def test_cli_apply_trust_manifest_input_root_rejects_row_outside_allowlist(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fileyard = repo_root / "apps" / "cli" / "fileyard.py"

    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    src = outside_root / "sample.png"
    payload = b"allowlist"
    src.write_bytes(payload)

    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    output_dir = tmp_path / "output"

    sha1 = hashlib.sha1(payload).hexdigest()
    row = {
        "path": str(src),
        "input_root": str(outside_root),
        "sha1": sha1,
        "hash8": sha1[:8],
        "file_mtime": "2025-01-01T12:00:00",
        "media_type": "image",
        "ai": {
            "kind": "截图",
            "category": "工作",
            "title": "白名单测试",
            "tags": [],
            "confidence": 0.9,
            "notes": "",
        },
        "error": "",
    }
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    cmd = [
        sys.executable,
        str(fileyard),
        "apply",
        "--manifest",
        str(manifest),
        "--output",
        str(output_dir),
        "--trust-manifest-input-root",
        "--manifest-input-root-allowlist",
        str(allowed_root),
    ]
    subprocess.run(cmd, check=True, cwd=str(repo_root))

    out_rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(out_rows) == 1
    assert "manifest input_root is outside the allowlist" in (out_rows[0].get("error") or "")
    assert src.exists()
