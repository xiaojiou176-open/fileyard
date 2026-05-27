import os
import subprocess
from pathlib import Path


def _script_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_clean_cache_script(tmp_path: Path):
    script_root = _script_root()
    script = script_root / "tooling" / "cleanup" / "prune_repo_runtime.sh"

    (tmp_path / "__pycache__").mkdir()
    (tmp_path / ".runtime-cache" / "tmp" / "case-a").mkdir(parents=True)
    (tmp_path / ".runtime-cache" / "tmp" / "case-a" / "temp.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".runtime-cache" / "logs").mkdir(parents=True)

    env = os.environ.copy()
    env["PWD"] = str(tmp_path)

    subprocess.run(["bash", str(script)], check=True, cwd=str(tmp_path), env=env)

    assert not (tmp_path / ".runtime-cache" / "tmp" / "case-a" / "temp.txt").exists()
    assert (tmp_path / ".runtime-cache" / "logs").exists()


def test_reset_workspace_state_recreates_movi_dir(tmp_path: Path):
    script_root = _script_root()
    script = script_root / "tooling" / "runtime" / "reset_workspace_state.sh"

    workspace = tmp_path / "workspace"
    movi_runs = workspace / ".fileyard" / "runs"
    movi_runs.mkdir(parents=True)
    env = os.environ.copy()
    env["FILEYARD_WORKSPACE_ROOT"] = str(workspace)

    subprocess.run([str(script)], cwd=str(script_root), env=env, check=True)
    assert (workspace / ".fileyard").exists()


def test_prune_repo_runtime_does_not_touch_machine_cache_or_workspace(tmp_path: Path):
    script = _script_root() / "tooling" / "cleanup" / "prune_repo_runtime.sh"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".runtime-cache" / "tmp" / "case").mkdir(parents=True)
    (repo / ".runtime-cache" / "tmp" / "case" / "x.txt").write_text("x", encoding="utf-8")
    machine_cache = tmp_path / "machine-cache"
    workspace = tmp_path / "workspace"
    (machine_cache / "pycache").mkdir(parents=True)
    (workspace / ".fileyard" / "runs").mkdir(parents=True)
    (machine_cache / "pycache" / "marker.pyc").write_text("x", encoding="utf-8")
    (workspace / ".fileyard" / "runs" / "marker.txt").write_text("x", encoding="utf-8")

    subprocess.run(["bash", str(script), str(repo)], check=True, cwd=str(repo))

    assert not (repo / ".runtime-cache" / "tmp" / "case" / "x.txt").exists()
    assert (machine_cache / "pycache" / "marker.pyc").exists()
    assert (workspace / ".fileyard" / "runs" / "marker.txt").exists()


def test_runtime_reset_requires_confirmation(tmp_path: Path):
    script_root = _script_root()
    script = script_root / "tooling" / "runtime" / "runtime_reset.sh"
    proc = subprocess.run(["bash", str(script)], cwd=str(script_root), text=True, capture_output=True)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2
    assert "--confirm-workspace-reset" in out


def test_prune_machine_cache_safe_and_rebuildable_modes(tmp_path: Path):
    script_root = _script_root()
    script = script_root / "tooling" / "cleanup" / "prune_machine_cache.sh"

    pycache = tmp_path / "machine" / "pycache"
    pip_cache = tmp_path / "machine" / "pip"
    npm_cache = tmp_path / "machine" / "npm"
    playwright = tmp_path / "machine" / "playwright"
    xdg_runtime = tmp_path / "machine" / "xdg" / "pytest-runtime"
    venv = tmp_path / "machine" / "venv" / "default"
    for target in (pycache, pip_cache, npm_cache, playwright, xdg_runtime, venv):
        target.mkdir(parents=True, exist_ok=True)
        (target / "marker.txt").write_text("x", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(pycache)
    env["PIP_CACHE_DIR"] = str(pip_cache)
    env["NPM_CONFIG_CACHE"] = str(npm_cache)
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(playwright)
    env["XDG_CACHE_HOME"] = str(tmp_path / "machine" / "xdg")
    env["FILEYARD_VENV_DIR"] = str(venv)

    subprocess.run(["bash", str(script), "--safe"], cwd=str(script_root), env=env, check=True)
    assert not pycache.exists()
    assert pip_cache.exists()
    assert npm_cache.exists()
    assert playwright.exists()
    assert xdg_runtime.exists()
    assert venv.exists()

    subprocess.run(["bash", str(script), "--rebuildable"], cwd=str(script_root), env=env, check=True)
    assert not pip_cache.exists()
    assert not npm_cache.exists()
    assert not playwright.exists()
    assert not xdg_runtime.exists()
    assert venv.exists()

    subprocess.run(["bash", str(script), "--rebuildable", "--include-venv"], cwd=str(script_root), env=env, check=True)
    assert not venv.exists()

    venv.mkdir(parents=True, exist_ok=True)
    (venv / "marker.txt").write_text("x", encoding="utf-8")
    subprocess.run(["bash", str(script), "--aggressive-host"], cwd=str(script_root), env=env, check=True)
    assert not venv.exists()


def test_prune_machine_cache_aggressive_host_removes_venv(tmp_path: Path):
    script_root = _script_root()
    script = script_root / "tooling" / "cleanup" / "prune_machine_cache.sh"

    pycache = tmp_path / "machine" / "pycache"
    pip_cache = tmp_path / "machine" / "pip"
    npm_cache = tmp_path / "machine" / "npm"
    playwright = tmp_path / "machine" / "playwright"
    xdg_runtime = tmp_path / "machine" / "xdg" / "pytest-runtime"
    venv = tmp_path / "machine" / "venv" / "default"
    for target in (pycache, pip_cache, npm_cache, playwright, xdg_runtime, venv):
        target.mkdir(parents=True, exist_ok=True)
        (target / "marker.txt").write_text("x", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(pycache)
    env["PIP_CACHE_DIR"] = str(pip_cache)
    env["NPM_CONFIG_CACHE"] = str(npm_cache)
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(playwright)
    env["XDG_CACHE_HOME"] = str(tmp_path / "machine" / "xdg")
    env["FILEYARD_VENV_DIR"] = str(venv)

    subprocess.run(["bash", str(script), "--aggressive-host"], cwd=str(script_root), env=env, check=True)
    assert not pycache.exists()
    assert not pip_cache.exists()
    assert not npm_cache.exists()
    assert not playwright.exists()
    assert not xdg_runtime.exists()
    assert not venv.exists()


def test_prune_machine_cache_dry_run_does_not_create_missing_targets(tmp_path: Path):
    script_root = _script_root()
    script = script_root / "tooling" / "cleanup" / "prune_machine_cache.sh"

    machine = tmp_path / "machine"
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(machine / "pycache")
    env["PIP_CACHE_DIR"] = str(machine / "pip")
    env["NPM_CONFIG_CACHE"] = str(machine / "npm")
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(machine / "playwright")
    env["XDG_CACHE_HOME"] = str(machine / "xdg")
    env["FILEYARD_VENV_DIR"] = str(machine / "venv" / "default")

    subprocess.run(["bash", str(script), "--rebuildable", "--dry-run"], cwd=str(script_root), env=env, check=True)

    assert not (machine / "pycache").exists()
    assert not (machine / "pip").exists()
    assert not (machine / "npm").exists()
    assert not (machine / "playwright").exists()
    assert not (machine / "xdg").exists()
    assert not (machine / "venv").exists()


def test_prune_workspace_runtime_preserves_manifests_and_preferences(tmp_path: Path):
    script_root = _script_root()
    script = script_root / "tooling" / "cleanup" / "prune_workspace_runtime.sh"

    workspace = tmp_path / "workspace"
    runs_root = workspace / ".fileyard" / "runs"
    artifact_root = workspace / ".fileyard" / "artifacts"
    manifest_root = workspace / ".fileyard" / "manifests"
    manifest_root.mkdir(parents=True)
    (manifest_root / "keep.jsonl").write_text("{}\n", encoding="utf-8")

    protected_runs = []
    for idx in range(51):
        run_dir = runs_root / f"run-{idx}"
        run_dir.mkdir(parents=True)
        (run_dir / "summary.json").write_text('{"status":"ok"}\n', encoding="utf-8")
        protected_runs.append(run_dir)

    old_run = runs_root / "run-old"
    old_run.mkdir(parents=True)
    (old_run / "summary.json").write_text('{"status":"ok"}\n', encoding="utf-8")

    report_old = artifact_root / "report" / "old-report.json"
    report_old.parent.mkdir(parents=True)
    report_old.write_text("{}", encoding="utf-8")

    failed_job = artifact_root / "web_api" / "jobs" / "job-failed"
    failed_job.mkdir(parents=True)
    (failed_job / "job.json").write_text('{"status":"failed"}\n', encoding="utf-8")

    preferences = artifact_root / "web_api" / "preferences" / "views.json"
    preferences.parent.mkdir(parents=True)
    preferences.write_text("{}", encoding="utf-8")

    very_old = 20 * 86400
    recent = 1 * 86400
    now = int(os.path.getmtime(script))
    os.utime(old_run, (now - very_old, now - very_old))
    os.utime(report_old, (now - very_old, now - very_old))
    os.utime(failed_job, (now - very_old, now - very_old))
    for idx, path in enumerate(protected_runs):
        age = recent + idx
        os.utime(path, (now - age, now - age))

    env = os.environ.copy()
    env["FILEYARD_RUN_BUNDLE_ROOT"] = str(runs_root)
    env["FILEYARD_ARTIFACT_ROOT"] = str(artifact_root)
    env["FILEYARD_MANIFEST_ROOT"] = str(manifest_root)

    subprocess.run(["bash", str(script)], cwd=str(script_root), env=env, check=True)

    assert old_run.exists() is False
    assert all(path.exists() for path in protected_runs)
    assert not report_old.exists()
    assert failed_job.exists()
    assert preferences.exists()
    assert (manifest_root / "keep.jsonl").exists()


def test_prune_workspace_runtime_keeps_newest_runs_by_mtime_not_name(tmp_path: Path):
    script_root = _script_root()
    script = script_root / "tooling" / "cleanup" / "prune_workspace_runtime.sh"

    workspace = tmp_path / "workspace"
    runs_root = workspace / ".fileyard" / "runs"
    artifact_root = workspace / ".fileyard" / "artifacts"
    manifest_root = workspace / ".fileyard" / "manifests"
    manifest_root.mkdir(parents=True)

    names = ["aaa-oldest"] + [f"slot-{idx:02d}" for idx in range(50)] + ["zzz-newest"]
    base_ts = 1_700_000_000
    for idx, name in enumerate(names):
        run_dir = runs_root / name
        run_dir.mkdir(parents=True)
        (run_dir / "summary.json").write_text('{"status":"ok"}\n', encoding="utf-8")
        ts = base_ts + idx
        os.utime(run_dir, (ts, ts))

    env = os.environ.copy()
    env["FILEYARD_RUN_BUNDLE_ROOT"] = str(runs_root)
    env["FILEYARD_ARTIFACT_ROOT"] = str(artifact_root)
    env["FILEYARD_MANIFEST_ROOT"] = str(manifest_root)

    subprocess.run(["bash", str(script)], cwd=str(script_root), env=env, check=True)

    assert not (runs_root / "aaa-oldest").exists()
    assert (runs_root / "zzz-newest").exists()


def test_prune_workspace_runtime_dry_run_does_not_create_missing_workspace_dirs(tmp_path: Path):
    script_root = _script_root()
    script = script_root / "tooling" / "cleanup" / "prune_workspace_runtime.sh"

    workspace = tmp_path / "workspace"
    run_root = workspace / ".fileyard" / "runs"
    artifact_root = workspace / ".fileyard" / "artifacts"
    manifest_root = workspace / ".fileyard" / "manifests"

    env = os.environ.copy()
    env["FILEYARD_RUN_BUNDLE_ROOT"] = str(run_root)
    env["FILEYARD_ARTIFACT_ROOT"] = str(artifact_root)
    env["FILEYARD_MANIFEST_ROOT"] = str(manifest_root)

    subprocess.run(["bash", str(script), "--dry-run"], cwd=str(script_root), env=env, check=True)

    assert not run_root.exists()
    assert not artifact_root.exists()
    assert not manifest_root.exists()


def test_prune_docker_runtime_rebuildable_and_aggressive_routes(tmp_path: Path):
    script_root = _script_root()
    script = script_root / "tooling" / "cleanup" / "prune_docker_runtime.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "docker-calls.log"
    docker = fake_bin / "docker"
    docker.write_text(
        f"""#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

log_path = Path({str(log_path)!r})
args = sys.argv[1:]
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(" ".join(args) + "\\n")

    if args == ["version", "--format", "{{.Server.Version}}"] or args == ["version"]:
        print("27.0.0")
        raise SystemExit(0)
    if args == ["system", "df", "-v"]:
        print(
            "Images space usage:\\n\\n"
        "REPOSITORY                     TAG      IMAGE ID       CREATED          SIZE      SHARED SIZE   UNIQUE SIZE   CONTAINERS\\n"
        "fileyard-ci                        local    abc123         1 hour ago       3.32GB    0B            3.323GB       0\\n\\n"
        "Containers space usage:\\n\\n"
        "CONTAINER ID   IMAGE   COMMAND   LOCAL VOLUMES   SIZE   CREATED   STATUS   NAMES\\n\\n"
        "Local Volumes space usage:\\n\\n"
        "VOLUME NAME                              LINKS     SIZE\\n"
        "fileyard-web-stack_movi_playwright           0         972MB\\n"
        "fileyard-web-stack_movi_venv                 0         401.6MB\\n"
        "fileyard-web-stack_movi_webui_node_modules   0         0B\\n\\n"
        "Build cache usage: 188MB\\n"
        )
        raise SystemExit(0)
    if args == ["system", "df", "-v", "--format", "json"]:
        print(
            '{{"Images":[{{"Repository":"fileyard-ci","Tag":"local","UniqueSize":"3.323GB","Size":"3.32GB"}}],'
            '"Containers":[],'
            '"Volumes":['
            '{{"Name":"fileyard-web-stack_movi_playwright","Size":"972MB","Mountpoint":"/docker/playwright"}},'
            '{{"Name":"fileyard-web-stack_movi_venv","Size":"401.6MB","Mountpoint":"/docker/venv"}},'
            '{{"Name":"fileyard-web-stack_movi_webui_node_modules","Size":"0B","Mountpoint":"/docker/node_modules"}}'
            '],'
            '"BuildCache":['
            '{{"Description":"[stage-1 6/8] COPY tooling/requirements.lock.txt '
            '/tmp/organizer-build/requirements.lock.txt","Size":"188MB"}}'
            ']}}'
        )
        raise SystemExit(0)
if args[:3] == ["image", "inspect", "fileyard-ci:local"]:
    print("884283278")
    raise SystemExit(0)
if args[:2] == ["volume", "inspect"]:
    name = args[2]
    print(f'{{"com.docker.compose.project":"fileyard-web-stack"}} /tmp/{{name}}')
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
if args[:2] == ["buildx", "prune"]:
    raise SystemExit(0)
if args[:2] == ["image", "rm"]:
    raise SystemExit(0)
if args[:2] == ["volume", "rm"]:
    raise SystemExit(0)
raise SystemExit(1)
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    subprocess.run(["bash", str(script), "--dry-run"], cwd=str(script_root), env=env, check=True)
    calls = log_path.read_text(encoding="utf-8")
    assert "buildx prune" not in calls
    assert (script_root / ".runtime-cache" / "logs" / "runtime-governance" / "summary.json").exists()

    subprocess.run(["bash", str(script), "--rebuildable"], cwd=str(script_root), env=env, check=True)
    calls = log_path.read_text(encoding="utf-8")
    assert "buildx prune -f --filter id=cache-1" in calls

    subprocess.run(
        ["bash", str(script), "--aggressive", "--include-image", "--include-volumes"],
        cwd=str(script_root),
        env=env,
        check=True,
    )
    calls = log_path.read_text(encoding="utf-8")
    assert "buildx prune -f --all" in calls
    assert "image rm -f fileyard-ci:local" in calls
    assert "volume rm -f fileyard-web-stack_movi_playwright" in calls
    assert "volume rm -f fileyard-web-stack_movi_venv" in calls
    assert "volume rm -f fileyard-web-stack_movi_webui_node_modules" in calls


def test_prune_shared_runner_workdirs_respects_worker_guard_and_keeps_runner_layers(tmp_path: Path):
    script_root = _script_root()
    script = script_root / "tooling" / "ci" / "prune_shared_runner_workdirs.sh"
    runner_root = tmp_path / "fileyard-shared-runners"
    workdir = runner_root / "temp-shared-pool-01" / "_work"
    externals = runner_root / "temp-shared-pool-01" / "externals"
    bin_dir = runner_root / "temp-shared-pool-01" / "bin"
    for target in (workdir, externals, bin_dir):
        target.mkdir(parents=True, exist_ok=True)
    (workdir / "payload").mkdir()
    (workdir / "payload" / "file.txt").write_text("x", encoding="utf-8")
    (externals / "keep.txt").write_text("x", encoding="utf-8")
    (bin_dir / "Runner.Listener").write_text("x", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ps = fake_bin / "ps"
    fake_ps.write_text("#!/usr/bin/env bash\nprintf '%s\\n' 'Runner.Worker active'\n", encoding="utf-8")
    fake_ps.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    blocked = subprocess.run(
        ["bash", str(script), "--root", str(runner_root)],
        cwd=str(script_root),
        env=env,
        text=True,
        capture_output=True,
    )
    assert blocked.returncode == 1
    assert (workdir / "payload" / "file.txt").exists()

    fake_ps.write_text("#!/usr/bin/env bash\nprintf '%s\\n' 'Runner.Listener idle'\n", encoding="utf-8")
    fake_ps.chmod(0o755)

    subprocess.run(["bash", str(script), "--root", str(runner_root)], cwd=str(script_root), env=env, check=True)
    assert not (workdir / "payload").exists()
    assert externals.exists()
    assert bin_dir.exists()
