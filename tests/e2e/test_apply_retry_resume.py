import hashlib
import json
import os
import subprocess
from pathlib import Path


def _row(path: Path, input_root: Path, sha1: str):
    return {
        "path": str(path),
        "input_root": str(input_root),
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


def test_apply_retry_errors_and_resume(tmp_path: Path):
    script_root = Path(__file__).resolve().parents[2]
    run_apply = script_root / "tooling" / "runtime" / "run_apply.sh"

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    a = input_dir / "a.png"
    b = input_dir / "b.png"
    a.write_bytes(b"a")
    b.write_bytes(b"b")

    sha1_a = hashlib.sha1(b"a").hexdigest()
    sha1_b = hashlib.sha1(b"b").hexdigest()

    row_a = _row(a, input_dir, sha1_a)
    row_a["error"] = "previous error"
    row_a["error_code"] = "AI_FAIL"
    row_a["status"] = "error"

    row_b = _row(b, input_dir, sha1_b)

    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join([json.dumps(row_a, ensure_ascii=False), json.dumps(row_b, ensure_ascii=False)]) + "\n",
        encoding="utf-8",
    )

    cmd = [
        str(run_apply),
        "--manifest",
        str(manifest),
        "--output",
        str(output_dir),
        "--input-root",
        str(input_dir),
        "--retry-errors",
        "--durability",
        "none",
    ]
    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = "1"
    subprocess.run(cmd, check=True, cwd=str(script_root), env=env)

    data = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(data) == 2
    for row in data:
        assert row.get("new_path")
        assert Path(row["new_path"]).exists()
        assert row.get("status") == "applied"

    row_a_updated = next(r for r in data if r.get("sha1") == sha1_a)
    assert row_a_updated.get("error") == ""
    assert not row_a_updated.get("error_code")

    cmd_resume = [
        str(run_apply),
        "--manifest",
        str(manifest),
        "--output",
        str(output_dir),
        "--input-root",
        str(input_dir),
        "--durability",
        "none",
        "--dry-run",
    ]
    subprocess.run(cmd_resume, check=True, cwd=str(script_root), env=env)

    data_resume = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(data_resume) == 2
    for row in data_resume:
        assert row.get("status") == "applied"
