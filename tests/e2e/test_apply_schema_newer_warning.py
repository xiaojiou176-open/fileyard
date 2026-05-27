import hashlib
import json
import subprocess
import sys
from pathlib import Path


def test_apply_schema_newer_warning(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    entry = repo_root / "apps" / "cli" / "fileyard.py"

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    src = input_dir / "sample.png"
    payload = b"schema-newer"
    src.write_bytes(payload)

    sha1 = hashlib.sha1(payload).hexdigest()
    row = {
        "schema_version": 999,
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

    cmd = [
        sys.executable,
        str(entry),
        "apply",
        "--manifest",
        str(manifest),
        "--output",
        str(output_dir),
        "--input-root",
        str(input_dir),
        "--dry-run",
        "--log-json",
    ]
    result = subprocess.run(cmd, cwd=str(repo_root), text=True, capture_output=True)

    assert result.returncode == 0
    combined = (result.stdout or "") + (result.stderr or "")
    events = []
    for line in combined.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event_obj = json.loads(line)
        except Exception:
            continue
        events.append(event_obj.get("event"))
    assert "schema_newer" in events
