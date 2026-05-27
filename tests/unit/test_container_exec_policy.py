from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _docker_socket_uri() -> str:
    return "unix://" + "/" + "/".join(("var", "run", "docker.sock"))


def _running_inside_container() -> bool:
    return Path("/.dockerenv").exists() or os.getenv("FILEMAN_IN_CONTAINER") == "1"


def _run_container_exec_with_fake_docker(
    tmp_path: Path,
    script_body: str,
    *,
    label: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tooling" / "scripts" / "container_exec.sh"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(script_body, encoding="utf-8")
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env.pop("FILEMAN_IN_CONTAINER", None)
    env.pop("FILEMAN_ALLOW_HOST_EXECUTION", None)
    env.pop("FILEMAN_CI_IMAGE", None)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["bash", str(script), "--label", label, "--", "echo", "ok"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_container_exec_forbids_host_fallback_in_ci() -> None:
    if _running_inside_container():
        pytest.skip("host-only policy assertion")
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tooling" / "scripts" / "container_exec.sh"
    env = os.environ.copy()
    env["CI"] = "1"
    env["FILEMAN_ALLOW_HOST_EXECUTION"] = "1"
    env.pop("FILEMAN_IN_CONTAINER", None)

    proc = subprocess.run(
        ["bash", str(script), "--label", "ci-policy", "--", "echo", "ok"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 1
    assert "forbidden in CI" in proc.stderr


def test_container_exec_forbids_host_fallback_in_github_actions() -> None:
    if _running_inside_container():
        pytest.skip("host-only policy assertion")
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tooling" / "scripts" / "container_exec.sh"
    env = os.environ.copy()
    env.pop("CI", None)
    env["GITHUB_ACTIONS"] = "true"
    env["FILEMAN_ALLOW_HOST_EXECUTION"] = "1"
    env.pop("FILEMAN_IN_CONTAINER", None)

    proc = subprocess.run(
        ["bash", str(script), "--label", "gha-policy", "--", "echo", "ok"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 1
    assert "forbidden in CI" in proc.stderr


def test_container_exec_rejects_spoofed_in_container_env_on_host() -> None:
    if _running_inside_container():
        pytest.skip("host-only policy assertion")
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tooling" / "scripts" / "container_exec.sh"
    env = os.environ.copy()
    env.pop("CI", None)
    env["FILEMAN_IN_CONTAINER"] = "1"
    env["FILEMAN_ALLOW_HOST_EXECUTION"] = "0"

    proc = subprocess.run(
        ["bash", str(script), "--label", "spoof-policy", "--", "echo", "ok"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 1
    assert "not inside a container" in proc.stderr


def test_container_exec_passthroughs_ci_gate_envs() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "tooling" / "scripts" / "container_exec.sh").read_text(encoding="utf-8")

    expected_vars = (
        "CI",
        "GITHUB_ACTIONS",
        "GITHUB_EVENT_NAME",
        "GITHUB_SHA",
        "GITHUB_REF",
        "GITHUB_REF_NAME",
        "GITHUB_WORKSPACE",
        "RUNNER_TEMP",
        "LINT_FRONTEND_SKIP_GEMINI_AUDIT",
        "GEMINI_UI_AUDIT_MODEL",
        "GEMINI_UI_AUDIT_TIMEOUT_MS",
    )

    for var_name in expected_vars:
        assert f"  {var_name}" in script


def test_container_exec_emits_context_aware_docker_diagnostic() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "tooling" / "scripts" / "container_exec.sh").read_text(encoding="utf-8")

    assert 'emit_docker_daemon_diagnostic "docker daemon readiness check"' in script
    assert "docker daemon returned HTTP 503" in script
    assert "docker context is invalid or missing" in script
    assert "docker client could not reach the daemon" in script
    assert "Docker socket path:" in script


def test_container_exec_compose_path_names_run_container_and_traps_cleanup() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "tooling" / "scripts" / "container_exec.sh").read_text(encoding="utf-8")

    assert 'COMPOSE_RUN_CONTAINER_NAME=""' in script
    assert 'COMPOSE_RUN_PID=""' in script
    assert "handle_compose_run_signal()" in script
    assert "trap 'handle_compose_run_signal 130' INT" in script
    assert "trap 'handle_compose_run_signal 143' TERM" in script
    assert "trap 'cleanup_compose_run_process; cleanup_compose_run_container' EXIT" in script
    assert "cleanup_compose_run_process()" in script
    assert 'docker compose "${COMPOSE_ARGS[@]}" run --name "$COMPOSE_RUN_CONTAINER_NAME" --rm -T' in script
    assert 'docker rm -f "$COMPOSE_RUN_CONTAINER_NAME"' in script


def test_container_exec_image_path_mounts_isolated_runtime_and_keeps_ci_env_passthrough(
    tmp_path: Path,
) -> None:
    if _running_inside_container():
        pytest.skip("host-only docker argument assertion")

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tooling" / "scripts" / "container_exec.sh"
    fake_docker = tmp_path / "docker"
    args_file = tmp_path / "docker-args.txt"
    fake_docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$FAKE_DOCKER_ARGS_FILE"\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env.pop("FILEMAN_IN_CONTAINER", None)
    env.pop("FILEMAN_ALLOW_HOST_EXECUTION", None)
    env["FILEMAN_CI_IMAGE"] = "fileman-ci:test"
    env["FAKE_DOCKER_ARGS_FILE"] = str(args_file)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"

    proc = subprocess.run(
        ["bash", str(script), "--label", "image-policy", "--", "echo", "ok"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0
    assert args_file.exists()

    docker_args = args_file.read_text(encoding="utf-8").splitlines()
    mounts: list[str] = []
    env_exports: list[str] = []
    for i, arg in enumerate(docker_args):
        if arg == "-v" and i + 1 < len(docker_args):
            mounts.append(docker_args[i + 1])
        if arg == "-e" and i + 1 < len(docker_args):
            env_exports.append(docker_args[i + 1])

    runtime_mounts = {mount.split(":", 1)[1]: mount.split(":", 1)[0] for mount in mounts if ":" in mount}
    assert f"{repo_root}:/workspace" in mounts
    assert runtime_mounts["/root/.cache/fileman/venv/default"].startswith("fileman-venv-")
    assert runtime_mounts["/root/.cache/fileman/playwright"].startswith("fileman-playwright-")
    assert runtime_mounts["/workspace/apps/webui/node_modules"].startswith("fileman-node-modules-")
    assert f"{repo_root}/.venv:/workspace/.venv" not in mounts

    assert "CI" in env_exports
    assert "GITHUB_SHA" in env_exports
    assert "GITHUB_RUN_ID" in env_exports


def test_container_exec_compose_fallback_builds_local_image_before_run(tmp_path: Path) -> None:
    if _running_inside_container():
        pytest.skip("host-only docker argument assertion")

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tooling" / "scripts" / "container_exec.sh"
    fake_docker = tmp_path / "docker"
    log_file = tmp_path / "docker-log.txt"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG_FILE"
if [ "$#" -ge 2 ] && [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
  exit 1
fi
if [ "$#" -ge 2 ] && [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$#" -ge 1 ] && [ "$1" = "build" ]; then
  exit 0
fi
if [ "$#" -ge 1 ] && [ "$1" = "compose" ]; then
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env.pop("FILEMAN_IN_CONTAINER", None)
    env.pop("FILEMAN_ALLOW_HOST_EXECUTION", None)
    env.pop("FILEMAN_CI_IMAGE", None)
    env["FAKE_DOCKER_LOG_FILE"] = str(log_file)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"

    proc = subprocess.run(
        ["bash", str(script), "--label", "compose-fallback", "--", "echo", "ok"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0
    calls = log_file.read_text(encoding="utf-8").splitlines()
    assert any(call == "compose version" for call in calls)
    assert any(
        call.startswith(
            f"build --file {repo_root / '.devcontainer' / 'Dockerfile'} --build-arg "
            "NODE_RUNTIME_IMAGE=node:24.8.0-bullseye@sha256:1f01014be94e1bbd6687191b5e33e376b8bb1a48abf9c42560a26c812587fdfb "
            f"--tag fileman-ci:local {repo_root}"
        )
        for call in calls
    )
    assert any("compose" in call and "run --name" in call and "--rm -T" in call and "fileman-ci" in call for call in calls)


def test_container_exec_reports_dns_failure_when_local_image_build_cannot_resolve_host(tmp_path: Path) -> None:
    if _running_inside_container():
        pytest.skip("host-only docker diagnostic assertion")

    proc = _run_container_exec_with_fake_docker(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ge 2 ] && [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$#" -ge 1 ] && [ "$1" = "info" ]; then
  exit 0
fi
if [ "$#" -ge 2 ] && [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
  exit 1
fi
if [ "$#" -ge 1 ] && [ "$1" = "build" ]; then
  echo "E: Failed to fetch http://deb.debian.org/debian/pool/main/c/curl/curl.deb  Temporary failure resolving 'deb.debian.org'" >&2
  exit 1
fi
exit 0
""",
        label="dns-build-failure",
    )

    assert proc.returncode == 1
    assert "failed to build local fallback image fileman-ci:local" in proc.stderr
    assert "Likely cause: DNS/network failure while building the local CI image." in proc.stderr
    assert "This gate can only run offline if fileman-ci:local already exists locally." in proc.stderr
    assert "Temporary failure resolving 'deb.debian.org'" in proc.stderr


def test_container_exec_reuses_existing_local_image_when_build_reports_already_exists(tmp_path: Path) -> None:
    if _running_inside_container():
        pytest.skip("host-only docker fallback assertion")

    marker = tmp_path / "built-marker"
    proc = _run_container_exec_with_fake_docker(
        tmp_path,
        f"""#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ge 2 ] && [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$#" -ge 1 ] && [ "$1" = "info" ]; then
  exit 0
fi
if [ "$#" -ge 2 ] && [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
  if [ -f "{marker}" ]; then
    exit 0
  fi
  exit 1
fi
if [ "$#" -ge 1 ] && [ "$1" = "build" ]; then
  touch "{marker}"
  echo 'ERROR: failed to solve: image "docker.io/library/fileman-ci:local": already exists' >&2
  exit 1
fi
if [ "$#" -ge 1 ] && [ "$1" = "compose" ]; then
  exit 0
fi
exit 0
""",
        label="existing-local-image",
    )

    assert proc.returncode == 0, proc.stderr


def test_container_exec_reports_docker_timeout_with_actionable_next_step(tmp_path: Path) -> None:
    if _running_inside_container():
        pytest.skip("host-only docker diagnostic assertion")

    proc = _run_container_exec_with_fake_docker(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ge 2 ] && [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$#" -ge 1 ] && [ "$1" = "info" ]; then
  sleep 2
  exit 1
fi
if [ "$#" -ge 2 ] && [ "$1" = "context" ] && [ "$2" = "show" ]; then
  printf 'desktop-linux\\n'
  exit 0
fi
if [ "$#" -ge 3 ] && [ "$1" = "context" ] && [ "$2" = "inspect" ]; then
  printf '[{"Endpoints":{"docker":{"Host":"unix:///tmp/fake-docker-timeout.sock"}}}]\\n'
  exit 0
fi
exit 0
""",
        label="docker-timeout",
        extra_env={"CONTAINER_EXEC_DOCKER_TIMEOUT_SECONDS": "1"},
    )

    assert proc.returncode == 1
    assert "timed out after 1s" in proc.stderr
    assert "Docker context: desktop-linux" in proc.stderr
    assert "Docker socket path: /tmp/fake-docker-timeout.sock" in proc.stderr
    assert "Docker CLI hung before the daemon answered" in proc.stderr


def test_container_exec_reports_invalid_docker_context(tmp_path: Path) -> None:
    if _running_inside_container():
        pytest.skip("host-only docker diagnostic assertion")

    proc = _run_container_exec_with_fake_docker(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ge 2 ] && [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$#" -ge 1 ] && [ "$1" = "info" ]; then
  echo 'Current context "desktop-linux" is not found on the file system.' >&2
  exit 1
fi
if [ "$#" -ge 2 ] && [ "$1" = "context" ] && [ "$2" = "show" ]; then
  printf 'desktop-linux\\n'
  exit 0
fi
if [ "$#" -ge 3 ] && [ "$1" = "context" ] && [ "$2" = "inspect" ]; then
  exit 1
fi
exit 0
""",
        label="docker-context",
    )

    assert proc.returncode == 1
    assert "docker context is invalid or missing" in proc.stderr
    assert "Docker context: desktop-linux" in proc.stderr
    assert "docker context ls" in proc.stderr
    assert 'Current context "desktop-linux" is not found' in proc.stderr


def test_container_exec_reports_docker_desktop_503(tmp_path: Path) -> None:
    if _running_inside_container():
        pytest.skip("host-only docker diagnostic assertion")

    proc = _run_container_exec_with_fake_docker(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ge 2 ] && [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$#" -ge 1 ] && [ "$1" = "info" ]; then
  echo 'request returned 503 Service Unavailable for API route and version' >&2
  echo 'http://%2Fvar%2Frun%2Fdocker.sock/_ping unsupported' >&2
  exit 1
fi
if [ "$#" -ge 2 ] && [ "$1" = "context" ] && [ "$2" = "show" ]; then
  printf 'desktop-linux\\n'
  exit 0
fi
if [ "$#" -ge 3 ] && [ "$1" = "context" ] && [ "$2" = "inspect" ]; then
  printf '[{"Endpoints":{"docker":{"Host":"{_docker_socket_uri()}"}}}]\\n'
  exit 0
fi
exit 0
""",
        label="docker-503",
    )

    assert proc.returncode == 1
    assert "docker daemon returned HTTP 503" in proc.stderr
    assert "Docker context: desktop-linux" in proc.stderr
    assert "engine API is not ready" in proc.stderr


def test_container_exec_reports_missing_socket_hint(tmp_path: Path) -> None:
    if _running_inside_container():
        pytest.skip("host-only docker diagnostic assertion")

    missing_socket = tmp_path / "missing.sock"
    proc = _run_container_exec_with_fake_docker(
        tmp_path,
        f"""#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ge 2 ] && [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$#" -ge 1 ] && [ "$1" = "info" ]; then
  echo 'Cannot connect to the Docker daemon at unix://{missing_socket}. Is the docker daemon running?' >&2
  exit 1
fi
if [ "$#" -ge 2 ] && [ "$1" = "context" ] && [ "$2" = "show" ]; then
  printf 'default\\n'
  exit 0
fi
if [ "$#" -ge 3 ] && [ "$1" = "context" ] && [ "$2" = "inspect" ]; then
  printf '[{{"Endpoints":{{"docker":{{"Host":"unix://{missing_socket}"}}}}}}]\\n'
  exit 0
fi
exit 0
""",
        label="docker-socket",
    )

    assert proc.returncode == 1
    assert "docker client could not reach the daemon" in proc.stderr
    assert f"Docker socket path: {missing_socket}" in proc.stderr
    assert "socket path does not exist" in proc.stderr
