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


def test_apply_dedupe_moves_duplicate(tmp_path: Path):
    script_root = Path(__file__).resolve().parents[2]
    run_apply = script_root / "tooling" / "runtime" / "run_apply.sh"

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    payload = b"same-content"
    a = input_dir / "a.png"
    b = input_dir / "b.png"
    a.write_bytes(payload)
    b.write_bytes(payload)

    sha1 = hashlib.sha1(payload).hexdigest()

    row_a = _row(a, input_dir, sha1)
    row_b = _row(b, input_dir, sha1)

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
        "--durability",
        "none",
    ]
    env = os.environ.copy()
    env["FILEYARD_ALLOW_HOST_EXECUTION"] = "1"
    subprocess.run(cmd, check=True, cwd=str(script_root), env=env)

    data = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(data) == 2
    applied = [row for row in data if row.get("status") == "applied"]
    duplicates = [row for row in data if row.get("status") == "duplicate"]
    assert len(applied) == 1
    assert len(duplicates) == 1

    applied_path = applied[0]["new_path"]
    dup_row = duplicates[0]
    assert dup_row.get("dedupe_of") == applied_path
    dup_path = Path(dup_row["new_path"])
    assert dup_path.exists()
    assert str(dup_path.parent).endswith(f"duplicates/{sha1[:8]}")
