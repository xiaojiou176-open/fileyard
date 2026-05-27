import subprocess
import sys
from pathlib import Path


def _checker(script_root: Path) -> Path:
    return script_root / "tooling" / "scripts" / "check_no_logs_no_merge.py"


def _python_bin(script_root: Path) -> Path:
    repo_root = script_root.parent
    venv_python = repo_root / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def _run_gate(script_root: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(tmp_path),
            "--mode",
            "all",
            "--scan-path",
            "src",
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _run_gate_mode(
    script_root: Path,
    repo_root: Path,
    mode: str,
    scan_path: str = "src",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(_python_bin(script_root)),
            str(_checker(script_root)),
            "--root",
            str(repo_root),
            "--mode",
            mode,
            "--scan-path",
            scan_path,
        ],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )


def test_no_logs_gate_passes_clean_files(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "ok.py").write_text(
        "import logging\n"
        "from packages.observability.logging_utils import log_event\n\n"
        "def run(logger):\n"
        "    log_event(\n"
        "        logger,\n"
        "        logging.ERROR,\n"
        "        'apply.move.fail',\n"
        "        'move failed with context',\n"
        "        error_type='PermissionError',\n"
        "        error_code='FS_PERMISSION_DENIED',\n"
        "        error_message='denied',\n"
        "        error_stack='',\n"
        "        error_retryable=False,\n"
        "        error_cause='permission',\n"
        "    )\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode == 0
    assert "passed" in (proc.stdout + proc.stderr)


def test_no_logs_gate_blocks_low_quality_phrase(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "bad.sh").write_text("echo 'something went wrong'\n", encoding="utf-8")

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "LOW_QUALITY_LOG_PHRASE" in out
    assert "bad.sh" in out


def test_no_logs_gate_blocks_missing_structured_error_fields(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "bad.py").write_text(
        "import logging\n"
        "from packages.observability.logging_utils import log_event\n\n"
        "def run(logger):\n"
        "    log_event(logger, logging.ERROR, 'apply.move.fail', 'failed')\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "MISSING_STRUCTURED_ERROR_FIELDS" in out
    assert "expected=error/error_* or exception context" in out


def test_no_logs_gate_allows_error_with_exception_context_only(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "ok_exc.py").write_text(
        "import logging\n"
        "from packages.observability.logging_utils import log_event\n\n"
        "def run(logger, exc):\n"
        "    log_event(logger, logging.ERROR, 'apply.move.fail', 'failed', exc_info=exc)\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode == 0
    assert "passed" in (proc.stdout + proc.stderr)


def test_no_logs_gate_does_not_require_error_fields_for_warning(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "warn.py").write_text(
        "import logging\n"
        "from packages.observability.logging_utils import log_event\n\n"
        "def run(logger):\n"
        "    log_event(logger, logging.WARNING, 'analyze_error', 'analyze warning', error_code='E_WARN')\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode == 0
    assert "passed" in (proc.stdout + proc.stderr)


def test_no_logs_gate_allows_phrase_with_explicit_marker(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "allowed.sh").write_text(
        "echo 'something went wrong' # no-logs-gate: allow-low-quality\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode == 0


def test_no_logs_gate_does_not_allow_marker_inside_string(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "marker_in_string.py").write_text(
        "def run():\n    msg = 'no-logs-gate: allow-low-quality'\n    print('something went wrong')\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "LOW_QUALITY_LOG_PHRASE" in out
    assert "marker_in_string.py" in out


def test_no_logs_gate_does_not_allow_marker_inside_same_line_string(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "marker_same_line.py").write_text(
        "def run():\n    print('something went wrong no-logs-gate: allow-low-quality')\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "LOW_QUALITY_LOG_PHRASE" in out
    assert "marker_same_line.py" in out


def test_no_logs_gate_marker_does_not_bypass_structured_error_fields(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "marker_structured.py").write_text(
        "def run(logger):\n    logger.error('oops')  # no-logs-gate: allow-low-quality\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "MISSING_STRUCTURED_ERROR_FIELDS" in out
    assert "marker_structured.py" in out


def test_no_logs_gate_blocks_low_quality_multiline_log_event_message(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "bad_multiline.py").write_text(
        "import logging\n"
        "from packages.observability.logging_utils import log_event\n\n"
        "def run(logger):\n"
        "    log_event(\n"
        "        logger,\n"
        "        logging.ERROR,\n"
        "        'apply.move.fail',\n"
        "        'something went wrong',\n"
        "        error_type='RuntimeError',\n"
        "        error_code='E_FAIL',\n"
        "    )\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "LOW_QUALITY_LOG_PHRASE" in out
    assert "bad_multiline.py" in out


def test_no_logs_gate_blocks_empty_event_name(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "bad_event.py").write_text(
        (
            "import logging\n"
            "from packages.observability.logging_utils import log_event\n\n"
            "def run(logger):\n"
            "    log_event(logger, logging.INFO, '', 'ok')\n"
        ),
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "MISSING_EVENT_NAME" in out
    assert "bad_event.py" in out


def test_no_logs_gate_blocks_low_quality_event_name(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "bad_event_name.py").write_text(
        "import logging\n"
        "from packages.observability.logging_utils import log_event\n\n"
        "def run(logger):\n"
        "    log_event(logger, logging.INFO, 'unknown', 'ok')\n",
        encoding="utf-8",
    )

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate(script_root, tmp_path)

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "LOW_QUALITY_EVENT_NAME" in out
    assert "bad_event_name.py" in out


def test_no_logs_gate_auto_mode_includes_unstaged_changes(tmp_path: Path):
    repo_root = tmp_path / "repo"
    src = repo_root / "src"
    src.mkdir(parents=True)
    target = src / "runtime.py"
    target.write_text("print('ok')\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=repo_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=repo_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_root, check=True, capture_output=True, text=True)

    # Unstaged low-quality runtime log should be picked up by --mode auto.
    target.write_text("print('something went wrong')\n", encoding="utf-8")

    script_root = Path(__file__).resolve().parents[2]
    proc = _run_gate_mode(script_root, repo_root, "auto")

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "LOW_QUALITY_LOG_PHRASE" in out
    assert "runtime.py" in out
