from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE_FILES = (
    ".github/workflows/ci.yml",
    ".github/workflows/nightly-drift-audit.yml",
    ".github/workflows/reusable-build-runtime-image.yml",
    "tooling/gates/verify_repo_final.sh",
    "tooling/gates/local_quality_gate.sh",
    "tooling/gates/quality_gate.sh",
    "tooling/gates/lint_frontend.sh",
    "tooling/gates/functional_gate.sh",
    "tooling/ci/resolve_dual_lane_gate.sh",
    "tooling/ci/detect_change_scope.sh",
    "tooling/ci/resolve_change_detection_gate.sh",
    "package.json",
    "apps/webui/package.json",
    "contracts/governance/required_checks_policy.yaml",
    "contracts/governance/done_signal_policy.yaml",
    "contracts/governance/project_positioning.yaml",
    "contracts/governance/public_claims_policy.yaml",
    "contracts/governance/hotspot_budget.yaml",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _script_path() -> Path:
    return _repo_root() / "tooling" / "scripts" / "check_ci_governance_regressions.py"


def _run_script(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_script_path()), "--root", str(repo_root)],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def _copy_fixture_repo(tmp_path: Path) -> Path:
    source_root = _repo_root()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    for relative_path in FIXTURE_FILES:
        source = source_root / relative_path
        target = repo_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return repo_root


def test_ci_governance_regressions_script_runs_on_current_repo() -> None:
    repo_root = _repo_root()
    proc = _run_script(repo_root)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ci_governance_regressions: passed" in (proc.stdout + proc.stderr)


def test_ci_governance_regressions_script_ignores_ci_topology_checks_owned_by_hardening(tmp_path: Path) -> None:
    repo_root = _copy_fixture_repo(tmp_path)
    ci_path = repo_root / ".github" / "workflows" / "ci.yml"
    ci_path.write_text(
        ci_path.read_text(encoding="utf-8").replace(
            "webui-build-test-self-hosted-fallback",
            "webui-build-test-shared-pool",
        ),
        encoding="utf-8",
    )

    proc = _run_script(repo_root)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ci_governance_regressions: passed" in (proc.stdout + proc.stderr)


def test_ci_governance_regressions_script_blocks_cross_file_governance_drift(tmp_path: Path) -> None:
    repo_root = _copy_fixture_repo(tmp_path)
    local_quality = repo_root / "tooling" / "gates" / "local_quality_gate.sh"
    local_quality.write_text(
        local_quality.read_text(encoding="utf-8").replace(
            "check_hotspot_budget.py",
            "check_hotspot_budget_removed.py",
        ),
        encoding="utf-8",
    )

    proc = _run_script(repo_root)
    output = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "local_quality_gate.sh must keep hotspot budget gate" in output


def test_ci_governance_regressions_script_does_not_own_merge_group_trigger(tmp_path: Path) -> None:
    repo_root = _copy_fixture_repo(tmp_path)
    ci_path = repo_root / ".github" / "workflows" / "ci.yml"
    ci_path.write_text(
        ci_path.read_text(encoding="utf-8").replace("  merge_group:\n    types: [checks_requested]\n", ""),
        encoding="utf-8",
    )

    proc = _run_script(repo_root)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ci_governance_regressions: passed" in (proc.stdout + proc.stderr)
