import hashlib
import json
import subprocess
import sys
from pathlib import Path


def test_apply_input_root_mismatch_generates_report(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    entry = repo_root / "apps" / "cli" / "fileman.py"

    input_dir = tmp_path / "input"
    other_root = tmp_path / "other"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    other_root.mkdir()

    src = input_dir / "sample.png"
    payload = b"root-mismatch"
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

    apply_cmd = [
        sys.executable,
        str(entry),
        "apply",
        "--manifest",
        str(manifest),
        "--output",
        str(output_dir),
        "--input-root",
        str(other_root),
    ]
    subprocess.run(apply_cmd, check=True, cwd=str(repo_root))

    assert src.exists()
    updated = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(updated) == 1
    row_out = updated[0]
    assert row_out.get("status") == "error"
    assert row_out.get("error_code") == "INPUT_ROOT_MISMATCH"

    report = tmp_path / "report.json"
    report_cmd = [
        sys.executable,
        str(entry),
        "report",
        "--manifest",
        str(manifest),
        "--out",
        str(report),
    ]
    subprocess.run(report_cmd, check=True, cwd=str(repo_root))

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["with_error"] == 1
    assert data["error_codes"]["INPUT_ROOT_MISMATCH"] == 1
    assert data["by_status"]["error"] == 1
