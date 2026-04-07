import subprocess
import sys
from pathlib import Path


def test_config_unknown_key_fail_fast(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    entry = repo_root / "apps" / "cli" / "movi_organizer.py"

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(b"x")

    manifest = tmp_path / "manifest.jsonl"
    config = tmp_path / "config.toml"
    config.write_text(
        f"""
[global]
log_json = true

[analyze]
input = \"{input_dir}\"
manifest = \"{manifest}\"
offline = true
unknown_key = \"oops\"
""",
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        str(entry),
        "analyze",
        "--config",
        str(config),
    ]
    result = subprocess.run(cmd, cwd=str(repo_root), text=True, capture_output=True)

    assert result.returncode != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "CONFIG_UNKNOWN_KEY" in combined
    assert "Config validation failed" in combined
    assert not manifest.exists()
