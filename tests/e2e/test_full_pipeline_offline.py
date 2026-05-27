import json
import os
import subprocess
import sys
from pathlib import Path


def test_full_pipeline_offline(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    venv_python = repo_root / ".runtime-cache" / "venv" / "default" / "bin" / "python"
    python_bin = venv_python if venv_python.exists() else Path(sys.executable)
    entry = repo_root / "apps" / "cli" / "fileman.py"

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    img = input_dir / "my_screenshot.png"
    pdf = input_dir / "report.pdf"
    img.write_bytes(b"img")
    pdf.write_bytes(b"pdf")

    manifest = tmp_path / "manifest.jsonl"

    analyze_cmd = [
        str(python_bin),
        str(entry),
        "analyze",
        "--input",
        str(input_dir),
        "--manifest",
        str(manifest),
        "--offline",
        "--durability",
        "none",
        "--workers",
        "1",
    ]
    subprocess.run(analyze_cmd, check=True, cwd=str(repo_root))
    assert manifest.exists()

    apply_cmd = [
        str(python_bin),
        str(entry),
        "apply",
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
    env["FILEMAN_ROLLBACK_HMAC_KEY"] = "e2e-test-rollback-key"
    subprocess.run(apply_cmd, check=True, cwd=str(repo_root), env=env)

    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 2
    new_paths = []
    for row in rows:
        new_path = row.get("new_path")
        assert new_path
        new_paths.append(Path(new_path))
        assert Path(new_path).exists()

    rollback_cmd = [
        str(python_bin),
        str(entry),
        "rollback",
        "--manifest",
        str(manifest),
        "--allowed-root",
        str(tmp_path),
    ]
    subprocess.run(rollback_cmd, check=True, cwd=str(repo_root), env=env)

    assert img.exists()
    assert pdf.exists()
    for path in new_paths:
        assert not path.exists()

    # Second rollback should be a no-op success: strict_integrity validates
    # signature/record shape, while non-executable rows are skipped safely.
    second = subprocess.run(rollback_cmd, check=False, cwd=str(repo_root), env=env, capture_output=True, text=True)
    assert second.returncode == 0
    assert "rollback_skip_missing_source" in (second.stdout + second.stderr)
    assert img.exists()
    assert pdf.exists()

    report = tmp_path / "report.json"
    report_cmd = [
        str(python_bin),
        str(entry),
        "report",
        "--manifest",
        str(manifest),
        "--out",
        str(report),
    ]
    subprocess.run(report_cmd, check=True, cwd=str(repo_root))
    report_data = json.loads(report.read_text(encoding="utf-8"))
    assert report_data["total"] == 2
