import hashlib
import json
import os
import subprocess
from pathlib import Path


def test_apply_report(tmp_path: Path):
    script_root = Path(__file__).resolve().parents[2]
    run_apply = script_root / "tooling" / "runtime" / "run_apply.sh"

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    src = input_dir / "sample.png"
    payload = b"report"
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
    report = tmp_path / "report.json"
    manifest.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    cmd = [
        str(run_apply),
        "--manifest",
        str(manifest),
        "--output",
        str(output_dir),
        "--input-root",
        str(input_dir),
        "--report",
        str(report),
        "--durability",
        "none",
    ]
    env = os.environ.copy()
    env["FILEYARD_ALLOW_HOST_EXECUTION"] = "1"
    subprocess.run(cmd, check=True, cwd=str(script_root), env=env)

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["total"] == 1
    assert data["by_status"]["applied"] == 1
    assert not Path(str(manifest) + ".partial").exists()
