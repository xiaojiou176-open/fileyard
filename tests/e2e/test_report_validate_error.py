import json
import subprocess
import sys
from pathlib import Path


def test_report_validate_rejects_bad_manifest(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    entry = repo_root / "apps" / "cli" / "fileman.py"

    manifest = tmp_path / "manifest.jsonl"
    out = tmp_path / "report.json"

    bad_row = {
        "path": 123,
        "input_root": str(tmp_path),
        "sha1": "",
        "hash8": "",
        "file_mtime": "",
        "media_type": "image",
        "ai": {"kind": "截图", "category": "工作", "title": "测试", "tags": []},
        "error": "",
    }
    manifest.write_text(json.dumps(bad_row, ensure_ascii=False) + "\n", encoding="utf-8")

    cmd = [
        sys.executable,
        str(entry),
        "report",
        "--manifest",
        str(manifest),
        "--out",
        str(out),
        "--validate",
    ]
    result = subprocess.run(cmd, cwd=str(repo_root), text=True, capture_output=True)

    assert result.returncode != 0
    combined = (result.stderr or "") + (result.stdout or "")
    assert "schema" in combined
    assert "line 1" in combined
    assert "$.path" in combined
    assert not out.exists()
