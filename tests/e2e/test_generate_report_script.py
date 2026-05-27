import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def test_generate_report_script(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tooling" / "runtime" / "generate_report.sh"

    manifest = tmp_path / "manifest.jsonl"
    out = tmp_path / "report.json"

    rows = [
        {
            "media_type": "image",
            "ai": {"kind": "截图", "category": "工作"},
            "status": "applied",
            "error": "",
            "error_code": "",
        },
        {
            "media_type": "audio",
            "ai": {"kind": "音频", "category": "其他"},
            "status": "error",
            "error": "fail",
            "error_code": "AI_FAIL",
        },
    ]
    manifest.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["FILEORGANIZE_ALLOW_EXTERNAL"] = "1"
    subprocess.run(
        [
            str(script),
            "--manifest",
            str(manifest),
            "--out",
            str(out),
        ],
        check=True,
        cwd=str(repo_root),
        env=env,
    )

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total"] == 2
    assert data["with_error"] == 1
    assert data["by_media_type"]["image"] == 1
    assert data["by_media_type"]["audio"] == 1
    assert data["by_status"]["applied"] == 1
    assert data["error_codes"]["AI_FAIL"] == 1
    assert not Path(str(out) + ".partial").exists()


def test_report_subcommand(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    entry = repo_root / "apps" / "cli" / "fileorganize.py"
    venv_python = repo_root / ".runtime-cache" / "venv" / "default" / "bin" / "python"
    python_bin = venv_python if venv_python.exists() else Path(sys.executable)

    manifest = tmp_path / "manifest.jsonl"
    out = tmp_path / "report.json"

    rows = [
        {
            "media_type": "image",
            "ai": {"kind": "截图", "category": "工作"},
            "status": "applied",
            "error": "",
        },
        {
            "media_type": "audio",
            "ai": {"kind": "音频", "category": "其他"},
            "status": "error",
            "error": "fail",
        },
    ]
    manifest.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    cmd = [
        str(python_bin),
        str(entry),
        "report",
        "--manifest",
        str(manifest),
        "--out",
        str(out),
    ]
    subprocess.run(cmd, check=True, cwd=str(repo_root))

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total"] == 2
    assert data["by_media_type"]["image"] == 1
    assert not Path(str(out) + ".partial").exists()


def test_generate_report_script_rejects_external_paths_by_default(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tooling" / "runtime" / "generate_report.sh"
    with tempfile.TemporaryDirectory(prefix="fileorganize-report-external-", dir="/var/tmp") as external_dir:
        external_root = Path(external_dir)
        manifest = external_root / "manifest.jsonl"
        out = external_root / "report.json"
        manifest.write_text('{"media_type":"image"}\n', encoding="utf-8")

        proc = subprocess.run(
            [
                str(script),
                "--manifest",
                str(manifest),
                "--out",
                str(out),
            ],
            check=False,
            cwd=str(repo_root),
            text=True,
            capture_output=True,
        )

        assert proc.returncode != 0
        assert "path must be inside repository" in ((proc.stderr or "") + (proc.stdout or ""))
        assert not out.exists()
