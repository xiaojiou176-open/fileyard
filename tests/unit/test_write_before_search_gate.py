import subprocess
import sys
from pathlib import Path


def _checker(script_root: Path) -> Path:
    return script_root / "tooling" / "scripts" / "check_write_before_search.py"


def _python_bin(script_root: Path) -> Path:
    repo_root = script_root.parent
    venv_python = repo_root / ".runtime-cache" / "venv" / "default" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def _run_gate(
    tmp_root: Path,
    keywords: str,
    mode: str = "all",
    diff_base: str = "",
    diff_head: str = "HEAD",
) -> subprocess.CompletedProcess[str]:
    script_root = Path(__file__).resolve().parents[2]
    cmd = [
        str(_python_bin(script_root)),
        str(_checker(script_root)),
        "--root",
        str(tmp_root),
        "--mode",
        mode,
        "--keywords",
        keywords,
    ]
    if mode == "diff-range":
        cmd.extend(["--diff-base", diff_base, "--diff-head", diff_head])

    return subprocess.run(
        cmd,
        cwd=str(script_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _git(tmp_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(tmp_root),
        capture_output=True,
        text=True,
        check=True,
    )


def _prepare_diff_repo(tmp_path: Path, updated_text: str) -> tuple[Path, str]:
    (tmp_path / "tests").mkdir(parents=True)
    (tmp_path / "packages" / "application").mkdir(parents=True)
    (tmp_path / "packages" / "application" / "pipeline.py").write_text(
        "def run_manifest():\n    return 'manifest'\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("项目目的\n技术栈\n导航手册\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("按需加载\n可执行门禁\n", encoding="utf-8")
    target = tmp_path / "tests" / "AGENTS.md"
    target.write_text("测试文档\n", encoding="utf-8")

    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "chore: base")
    base = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    target.write_text(updated_text, encoding="utf-8")
    _git(tmp_path, "add", "tests/AGENTS.md")
    _git(tmp_path, "commit", "-m", "docs: update tests guide")
    return tmp_path, base


def test_write_before_search_gate_passes_with_keyword_matches(tmp_path: Path) -> None:
    (tmp_path / "packages" / "application").mkdir(parents=True)
    (tmp_path / "packages" / "application" / "pipeline.py").write_text(
        "def run_manifest():\n    return 'manifest'\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("write-before-search\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("navigation\n", encoding="utf-8")

    proc = _run_gate(tmp_path, "manifest")

    assert proc.returncode == 0
    assert "write_before_search: passed" in (proc.stdout + proc.stderr)


def test_write_before_search_gate_blocks_when_keyword_scan_finds_nothing(tmp_path: Path) -> None:
    (tmp_path / "packages" / "application").mkdir(parents=True)
    (tmp_path / "packages" / "application" / "pipeline.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("write-before-search\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("navigation\n", encoding="utf-8")

    proc = _run_gate(tmp_path, "this_should_not_match_anything_123")

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "no matches for required `rg -n` keyword scan" in out


def test_write_before_search_gate_blocks_missing_tests_module_evidence(tmp_path: Path) -> None:
    repo_root, base = _prepare_diff_repo(tmp_path, "仅更新说明，不含门禁关键词\n")

    proc = _run_gate(
        repo_root,
        "manifest|导航",
        mode="diff-range",
        diff_base=base,
        diff_head="HEAD",
    )

    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "missing module-level search evidence" in out
    assert "tests:" in out


def test_write_before_search_gate_passes_with_tests_module_evidence(tmp_path: Path) -> None:
    repo_root, base = _prepare_diff_repo(
        tmp_path,
        "写前必搜\n可执行门禁\npytest e2e unit fixture\n",
    )

    proc = _run_gate(
        repo_root,
        "manifest|导航",
        mode="diff-range",
        diff_base=base,
        diff_head="HEAD",
    )

    assert proc.returncode == 0
    assert "write_before_search: passed" in (proc.stdout + proc.stderr)
