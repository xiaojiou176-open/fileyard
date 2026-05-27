from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def _prepare_repo(tmp_path: Path) -> tuple[Path, Path]:
    source_root = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    (repo / "contracts" / "runtime").mkdir(parents=True)
    (repo / "tooling" / "scripts").mkdir(parents=True)

    contract = yaml.safe_load((source_root / "contracts" / "runtime" / "filesystem_layout.yaml").read_text(encoding="utf-8"))
    contract["budgets_mb"]["repo_runtime_warn"] = 0.01
    contract["budgets_mb"]["repo_runtime_error"] = 9999
    contract["budgets_mb"]["machine_cache_warn"] = 0.01
    contract["budgets_mb"]["machine_cache_error"] = 9999
    contract["retention"]["workspace_runs_days"] = 1
    contract["retention"]["workspace_runs_keep_latest"] = 2
    contract["retention"]["workspace_artifacts_days"] = 1
    contract["retention"]["workspace_failed_artifacts_days"] = 30
    (repo / "contracts" / "runtime" / "filesystem_layout.yaml").write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )

    script_path = source_root / "tooling" / "scripts" / "check_cache_size.py"
    target = repo / "tooling" / "scripts" / "check_cache_size.py"
    target.write_text(script_path.read_text(encoding="utf-8"), encoding="utf-8")
    for helper_name in ("docker_runtime_inventory.py", "runtime_governance_report.py"):
        helper_src = source_root / "tooling" / "scripts" / helper_name
        helper_dst = repo / "tooling" / "scripts" / helper_name
        helper_dst.write_text(helper_src.read_text(encoding="utf-8"), encoding="utf-8")
    return repo, target


def _write_fake_docker(bin_dir: Path) -> Path:
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
from __future__ import annotations

import sys

args = sys.argv[1:]
if args == ["version", "--format", "{{.Server.Version}}"]:
    print("27.0.0")
    raise SystemExit(0)
if args == ["system", "df", "-v"]:
    print(
        "Images space usage:\\n\\n"
        "REPOSITORY                     TAG      IMAGE ID       CREATED          SIZE      SHARED SIZE   UNIQUE SIZE   CONTAINERS\\n"
        "fileman-ci                        local    abc123         1 hour ago       3.32GB    0B            3.323GB       0\\n\\n"
        "Containers space usage:\\n\\n"
        "CONTAINER ID   IMAGE   COMMAND   LOCAL VOLUMES   SIZE   CREATED   STATUS   NAMES\\n\\n"
        "Local Volumes space usage:\\n\\n"
        "VOLUME NAME                              LINKS     SIZE\\n"
        "fileman-web-stack_fileman_playwright           0         972MB\\n"
        "fileman-web-stack_fileman_venv                 0         401.6MB\\n"
        "fileman-web-stack_fileman_webui_node_modules   0         0B\\n\\n"
        "Build cache usage: 188MB\\n"
    )
    raise SystemExit(0)
if args[:3] == ["image", "inspect", "fileman-ci:local"]:
    print("884283278")
    raise SystemExit(0)
if args[:2] == ["volume", "inspect"]:
    name = args[2]
    print(f'{{"com.docker.compose.project":"fileman-web-stack"}} /tmp/{name}')
    raise SystemExit(0)
if args == ["buildx", "du", "--verbose"]:
    print(
        "ID:           cache-1\\n"
        "Size:         188MB\\n"
        "Description:  [stage-1 6/8] COPY tooling/requirements.lock.txt /tmp/organizer-build/requirements.lock.txt\\n\\n"
        "ID:           cache-2\\n"
        "Size:         32MB\\n"
        "Description:  unrelated cache\\n"
    )
    raise SystemExit(0)
raise SystemExit(1)
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return docker


def test_check_cache_size_reports_four_sections_and_commands(tmp_path: Path) -> None:
    repo, script = _prepare_repo(tmp_path)
    (repo / ".runtime-cache" / "logs").mkdir(parents=True)
    (repo / ".runtime-cache" / "logs" / "step.log").write_text("x\n", encoding="utf-8")

    machine_root = tmp_path / "machine"
    pycache = machine_root / "pycache"
    pycache.mkdir(parents=True)
    (pycache / "x.pyc").write_text("x", encoding="utf-8")

    workspace = tmp_path / "workspace"
    run_root = workspace / ".fileman" / "runs"
    artifact_root = workspace / ".fileman" / "artifacts"
    for idx in range(3):
        run_dir = run_root / f"run-{idx}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "summary.json").write_text('{"status":"ok"}\n', encoding="utf-8")
        os.utime(run_dir, (1, 1))
    old_report = artifact_root / "report" / "old.json"
    old_report.parent.mkdir(parents=True)
    old_report.write_text("{}", encoding="utf-8")
    os.utime(old_report, (1, 1))

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_docker(fake_bin)

    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(pycache)
    env["PIP_CACHE_DIR"] = str(machine_root / "pip")
    env["NPM_CONFIG_CACHE"] = str(machine_root / "npm")
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(machine_root / "playwright")
    env["XDG_CACHE_HOME"] = str(machine_root / "xdg")
    env["FILEMAN_RUN_BUNDLE_ROOT"] = str(run_root)
    env["FILEMAN_ARTIFACT_ROOT"] = str(artifact_root)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    proc = subprocess.run(
        [sys.executable, str(script), "--root", str(repo)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "==> Repo-local runtime report" in out
    assert "==> Machine-cache report" in out
    assert "==> Workspace evidence retention report" in out
    assert "==> Docker runtime report" in out
    assert "bash tooling/cleanup/prune_repo_runtime.sh" in out
    assert "bash tooling/cleanup/prune_machine_cache.sh --safe" in out
    assert "bash tooling/cleanup/prune_machine_cache.sh --aggressive-host" in out
    assert "bash tooling/cleanup/prune_workspace_runtime.sh --dry-run" in out
    assert "bash tooling/cleanup/prune_docker_runtime.sh --dry-run" in out
    assert (repo / ".runtime-cache" / "logs" / "runtime-governance" / "summary.json").exists()


def test_check_cache_size_json_output_contains_expected_sections(tmp_path: Path) -> None:
    repo, script = _prepare_repo(tmp_path)
    (repo / ".runtime-cache" / "logs").mkdir(parents=True)
    (repo / ".runtime-cache" / "logs" / "step.log").write_text("x\n", encoding="utf-8")

    machine_root = tmp_path / "machine"
    pycache = machine_root / "pycache"
    pycache.mkdir(parents=True)
    (pycache / "x.pyc").write_text("x", encoding="utf-8")

    workspace = tmp_path / "workspace"
    run_root = workspace / ".fileman" / "runs"
    artifact_root = workspace / ".fileman" / "artifacts"
    run_dir = run_root / "run-0"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text('{"status":"ok"}\n', encoding="utf-8")
    os.utime(run_dir, (1, 1))

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_docker(fake_bin)

    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(pycache)
    env["PIP_CACHE_DIR"] = str(machine_root / "pip")
    env["NPM_CONFIG_CACHE"] = str(machine_root / "npm")
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(machine_root / "playwright")
    env["XDG_CACHE_HOME"] = str(machine_root / "xdg")
    env["FILEMAN_RUN_BUNDLE_ROOT"] = str(run_root)
    env["FILEMAN_ARTIFACT_ROOT"] = str(artifact_root)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    proc = subprocess.run(
        [sys.executable, str(script), "--root", str(repo), "--json"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert "repo_local" in payload
    assert "machine_cache" in payload
    assert "workspace_evidence" in payload
    assert "docker_runtime" in payload
    image_entry = next(entry for entry in payload["docker_runtime"]["entries"] if entry["path_or_object"] == "docker image fileman-ci:local")
    assert image_entry["policy_size_mb"] > 0
    governance_summary = repo / ".runtime-cache" / "logs" / "runtime-governance" / "summary.json"
    assert governance_summary.exists()
    summary_payload = json.loads(governance_summary.read_text(encoding="utf-8"))
    assert summary_payload["command"] == "check_cache_size"
    assert (repo / ".runtime-cache" / "logs" / "runtime-governance" / "summary.json").exists()
