from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_observability_baseline_targets_current_logging_module() -> None:
    script = (REPO_ROOT / "tooling" / "gates" / "check_observability_baseline.sh").read_text(encoding="utf-8")

    assert 'root / "packages" / "observability" / "logging_utils.py"' in script
    assert 'root / "packages" / "core" / "pipeline" / "logging_utils.py"' not in script


def test_rollback_rto_uses_current_cli_entrypoint_and_repo_root() -> None:
    script = (REPO_ROOT / "tooling" / "gates" / "check_rollback_rto.sh").read_text(encoding="utf-8")

    assert '"$REPO_ROOT/apps/cli/fileman.py"' in script
    assert "repo_root = Path(sys.argv[1]).resolve()" in script
    assert "sys.path.insert(0, str(repo_root))" in script
    assert 'runtime_temp_root = repo_root / ".runtime-cache" / "temp"' in script
    assert "runtime_temp_root.mkdir(parents=True, exist_ok=True)" in script
    assert "dir=str(runtime_temp_root)" in script
    assert "cwd=str(repo_root)" in script
    assert '"$ROOT/fileman.py"' not in script
    assert 'Path.cwd() / "脚本"' not in script


def test_env_contract_baseline_prefers_current_gate_module_path() -> None:
    script = (REPO_ROOT / "tooling" / "scripts" / "update_env_contract_baseline.py").read_text(encoding="utf-8")

    assert 'modern_gate_path = repo_root / "tooling" / "scripts" / "check_env_contract.py"' in script
    assert 'legacy_gate_path = repo_root / "脚本" / "scripts" / "check_env_contract.py"' in script


def test_atomic_commit_gate_prefers_current_baseline_path() -> None:
    script = (REPO_ROOT / "tooling" / "scripts" / "check_atomic_commits.py").read_text(encoding="utf-8")

    assert 'MODERN_BASELINE_PATH = REPO_ROOT / "contracts" / "governance" / "baselines" / "gate_history_baseline.json"' in script
    assert 'LEGACY_BASELINE_PATH = REPO_ROOT / "脚本" / "config" / "governance-baselines" / "gate_history_baseline.json"' in script
