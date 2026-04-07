import subprocess
import sys
from pathlib import Path


def test_analyze_preflight_limit_blocks(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    entry = repo_root / "apps" / "cli" / "movi_organizer.py"

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.png").write_bytes(b"a")
    (input_dir / "b.png").write_bytes(b"b")

    manifest = tmp_path / "manifest.jsonl"

    cmd = [
        sys.executable,
        str(entry),
        "analyze",
        "--input",
        str(input_dir),
        "--manifest",
        str(manifest),
        "--offline",
        "--max-files",
        "1",
        "--log-json",
    ]
    result = subprocess.run(cmd, cwd=str(repo_root), text=True, capture_output=True)

    assert result.returncode != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "PREFLIGHT_LIMIT" in combined
    assert not manifest.exists()
