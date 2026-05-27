import json
import subprocess
import sys
from pathlib import Path


def test_analyze_with_config_file(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    venv_python = repo_root / ".runtime-cache" / "venv" / "default" / "bin" / "python"
    python_bin = venv_python if venv_python.exists() else Path(sys.executable)
    entry = repo_root / "apps" / "cli" / "fileman.py"

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "my_screenshot.png").write_bytes(b"x")
    (input_dir / "doc.pdf").write_bytes(b"y")

    manifest = tmp_path / "manifest.jsonl"

    config = tmp_path / "config.toml"
    config.write_text(
        f"""
[analyze]
input = "{input_dir}"
manifest = "{manifest}"
offline = true
durability = "none"
workers = 1
""",
        encoding="utf-8",
    )

    cmd = [
        str(python_bin),
        str(entry),
        "analyze",
        "--config",
        str(config),
    ]
    subprocess.run(cmd, check=True, cwd=str(repo_root))

    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 2
    kinds = sorted([(r.get("ai") or {}).get("kind", "") for r in rows])
    assert kinds == ["截图", "文档"]
