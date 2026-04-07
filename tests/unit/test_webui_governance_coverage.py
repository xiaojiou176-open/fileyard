from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _script_root() -> Path:
    return Path(__file__).resolve().parents[2] / "tooling"


def _python_bin() -> Path:
    repo_root = _script_root().parent
    venv_python = repo_root / ".runtime-cache" / "venv" / "default" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd)


def _init_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@example.com")
    _git(repo, "config", "user.name", "CI Bot")


def test_webui_readme_uses_generated_api_contract_block() -> None:
    readme = (_script_root().parent / "apps" / "webui" / "README.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN GENERATED: webui-api-contract -->" in readme
    assert "<!-- END GENERATED: webui-api-contract -->" in readme
    assert "generated reference" in readme


def test_runtime_topology_reference_exists_and_is_linked_from_overviews() -> None:
    repo_root = _script_root().parent
    runtime_ref = (repo_root / "docs" / "reference" / "runtime_topology.generated.md").read_text(encoding="utf-8")
    assert "AUTO-GENERATED" in runtime_ref
    for rel in ("README.md", "docs/usage.md", "docs/architecture.md"):
        text = (repo_root / rel).read_text(encoding="utf-8")
        assert "runtime_topology.generated.md" in text


def test_webui_package_pins_security_overrides_for_transitive_vulns() -> None:
    package_json = json.loads((_script_root().parent / "apps" / "webui" / "package.json").read_text(encoding="utf-8"))
    overrides = package_json.get("overrides", {})

    assert overrides.get("flatted") == "3.4.2"
    assert overrides.get("undici") == "7.24.1"


def test_write_before_search_gate_covers_webui_scope(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    webui_page = repo / "apps" / "webui" / "src" / "pages"
    webui_page.mkdir(parents=True)

    _init_repo(repo)
    (webui_page / "dashboard-page.tsx").write_text(
        "export function DashboardPageComponent() { return <div>dashboard component</div>; }\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore: init")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()

    (webui_page / "dashboard-page.tsx").write_text(
        "export function DashboardPageComponent() { return <div>dashboard route component</div>; }\n",
        encoding="utf-8",
    )
    _git(repo, "add", "apps/webui/src/pages/dashboard-page.tsx")
    _git(repo, "commit", "-m", "feat: update dashboard")

    checker = _script_root() / "scripts" / "check_write_before_search.py"
    proc = _run(
        [
            str(_python_bin()),
            str(checker),
            "--root",
            str(repo),
            "--mode",
            "diff-range",
            "--diff-base",
            base,
            "--diff-head",
            "HEAD",
            "--keywords",
            "dashboard|route|component",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0
    assert "write_before_search: passed" in out
    assert "apps/webui/src/pages/dashboard-page.tsx" in out


def test_no_logs_gate_scans_webui_typescript_logs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    webui_src = repo / "apps" / "webui" / "src"
    webui_src.mkdir(parents=True)
    (webui_src / "bad-log.ts").write_text("console.error('something went wrong')\n", encoding="utf-8")

    checker = _script_root() / "scripts" / "check_no_logs_no_merge.py"
    proc = _run(
        [
            str(_python_bin()),
            str(checker),
            "--root",
            str(repo),
            "--mode",
            "all",
            "--scan-path",
            "apps/webui/src",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "LOW_QUALITY_LOG_PHRASE" in out
    assert "bad-log.ts" in out
