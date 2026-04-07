import os
import subprocess
from pathlib import Path


def test_run_pytest_with_heartbeat_emits_heartbeat_and_progress():
    script_root = Path(__file__).resolve().parents[2]
    script = script_root / "tooling" / "scripts" / "run_pytest_with_heartbeat.sh"
    env = os.environ.copy()
    env["HEARTBEAT_INTERVAL_SECONDS"] = "1"
    env["PYTEST_MAX_DURATION_SECONDS"] = "10"

    proc = subprocess.run(
        [
            "bash",
            str(script),
            "bash",
            "-lc",
            "echo unit-start; sleep 1.2; echo unit-done",
        ],
        cwd=str(script_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0
    assert "[pytest-heartbeat]" in out
    assert "progress=" in out
    assert "unit-done" in out


def test_run_pytest_with_heartbeat_times_out_long_command():
    script_root = Path(__file__).resolve().parents[2]
    script = script_root / "tooling" / "scripts" / "run_pytest_with_heartbeat.sh"
    env = os.environ.copy()
    env["HEARTBEAT_INTERVAL_SECONDS"] = "1"
    env["PYTEST_MAX_DURATION_SECONDS"] = "1"

    proc = subprocess.run(
        [
            "bash",
            str(script),
            "bash",
            "-lc",
            "echo unit-start; sleep 5; echo unit-done",
        ],
        cwd=str(script_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 124
    assert "exceeded PYTEST_MAX_DURATION_SECONDS=1" in out
