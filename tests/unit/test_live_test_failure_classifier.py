import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_classifier():
    script_root = Path(__file__).resolve().parents[2]
    script_path = script_root / "tooling" / "scripts" / "live_test_failure_classifier.py"
    spec = importlib.util.spec_from_file_location("live_test_failure_classifier", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.classify_live_failure


classify_live_failure = _load_classifier()


def _python_bin(script_root: Path) -> Path:
    repo_root = script_root.parent
    venv_python = repo_root / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def test_classify_live_failure_business_has_priority_over_network_markers():
    text = "LIVE_ERROR_CLASS=business AssertionError: request not ok; upstream returned 503 timeout"
    assert classify_live_failure(text) == "business"


def test_classify_live_failure_detects_network_jitter():
    text = "Connection reset by peer; LIVE_ERROR_CLASS=network-timeout"
    assert classify_live_failure(text) == "network-timeout"
    jitter_text = "Connection reset by peer; transient dns name resolution failure"
    assert classify_live_failure(jitter_text) == "network-jitter"


def test_classify_live_failure_uses_latest_explicit_marker_when_both_exist():
    text = (
        "first attempt failed LIVE_ERROR_CLASS=network-timeout; "
        "second attempt failed LIVE_ERROR_CLASS=business AssertionError: invalid format"
    )
    assert classify_live_failure(text) == "business"


def test_classify_live_failure_is_case_insensitive():
    network_text = "ERROR: ECONNREFUSED while calling upstream"
    timeout_text = "ERROR: request timed out while calling upstream"
    business_text = "ASSERTIONERROR: invalid format"
    assert classify_live_failure(network_text) == "network-jitter"
    assert classify_live_failure(timeout_text) == "network-timeout"
    assert classify_live_failure(business_text) == "business"


def test_classify_live_failure_unknown_when_no_pattern():
    assert classify_live_failure("some unrelated message") == "unknown"


def test_classifier_cli_reads_file_and_prints_classification(tmp_path: Path):
    log_file = tmp_path / "live.log"
    log_file.write_text("AssertionError: invalid format", encoding="utf-8")

    script_root = Path(__file__).resolve().parents[2]
    checker = script_root / "tooling" / "scripts" / "live_test_failure_classifier.py"
    proc = subprocess.run(
        [str(_python_bin(script_root)), str(checker), "--log-file", str(log_file)],
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stdout.strip() == "business"
