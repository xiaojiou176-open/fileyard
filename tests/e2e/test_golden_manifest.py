import json
import os
import subprocess
from pathlib import Path


def test_golden_offline_manifest(tmp_path: Path):
    script_root = Path(__file__).resolve().parents[2]
    run_analyze = script_root / "tooling" / "runtime" / "run_analyze.sh"

    input_dir = script_root / "tests" / "fixtures" / "golden_input"
    expected = script_root / "tests" / "fixtures" / "golden_expected" / "manifest.jsonl"
    manifest = tmp_path / "manifest.jsonl"
    report = tmp_path / "report_summary.json"

    cmd = [
        str(run_analyze),
        "--input",
        str(input_dir),
        "--manifest",
        str(manifest),
        "--offline",
        "--run-id",
        "test_run_0001",
        "--generator-version",
        "4.0.0",
        "--durability",
        "none",
        "--workers",
        "1",
        "--report",
        str(report),
    ]
    env = os.environ.copy()
    env["MOVI_ALLOW_HOST_EXECUTION"] = "1"
    subprocess.run(cmd, check=True, cwd=str(script_root), env=env)

    actual_rows = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row["path"] = row["path"].replace(str(input_dir.resolve()), "<INPUT_ROOT>")
        row["input_root"] = row["input_root"].replace(str(input_dir.resolve()), "<INPUT_ROOT>")
        # Git checkout metadata can differ by CI/runtime image, normalize volatile fields.
        if "file_mtime" in row:
            row["file_mtime"] = "<FILE_MTIME>"
        if "mime" in row:
            row["mime"] = "<MIME>"
        if "run_id" in row:
            row["run_id"] = "<RUN_ID>"
        actual_rows.append(row)

    expected_rows = [json.loads(line) for line in expected.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in expected_rows:
        if "file_mtime" in row:
            row["file_mtime"] = "<FILE_MTIME>"
        if "mime" in row:
            row["mime"] = "<MIME>"
        if "run_id" in row:
            row["run_id"] = "<RUN_ID>"
    assert actual_rows == expected_rows
    assert report.exists()
    assert not Path(str(manifest) + ".partial").exists()
