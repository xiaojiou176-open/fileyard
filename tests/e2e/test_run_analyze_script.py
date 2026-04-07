import os
import subprocess
from pathlib import Path


def test_run_analyze_script_empty_dir(tmp_path: Path):
    script_root = Path(__file__).resolve().parents[2]
    run_analyze = script_root / "tooling" / "runtime" / "run_analyze.sh"

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    manifest = tmp_path / "manifest.jsonl"

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = "dummy"
    env["GEMINI_MODEL"] = "gemini-3-flash-preview"
    env["MOVI_ALLOW_HOST_EXECUTION"] = "1"

    cmd = [str(run_analyze), "--input", str(input_dir), "--manifest", str(manifest)]
    subprocess.run(cmd, check=True, cwd=str(script_root), env=env)

    assert not manifest.exists()
