from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", str(repo)], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Codex"], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "codex@example.com"], check=True, text=True, capture_output=True)
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True, text=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, text=True, capture_output=True)
    return repo


def _write_contracts(repo: Path, *, include_tracked_policy: bool = True) -> None:
    governance = repo / "contracts" / "governance"
    governance.mkdir(parents=True)
    (governance / "root_allowlist.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "canonical_tracked_entries:",
                "  - README.md",
                "local_only_entries:",
                "  - .agents",
                "  - .runtime-cache",
                "local_only_tracking:",
                "  mode: fail-close",
                "  enforcement_target: git-tracked-surface",
                "  require_change_control_tracked_policy: true",
                "  entries:",
                "    - .agents",
                "    - .runtime-cache",
                "entry_purposes:",
                "  README.md: public root fixture",
                "  .agents: repo-local plans and conversations",
                "  .runtime-cache: runtime-only artifacts",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "version: 1",
        "entries:",
        "  README.md:",
        "    owner: repo",
        "    change_class: public-doc",
        "    approval_rule: architecture-review",
        "  .agents:",
        "    owner: repo",
        "    change_class: local-only",
        "    approval_rule: architecture-review",
    ]
    if include_tracked_policy:
        lines.extend(
            [
                "    tracked_policy: must-remain-untracked",
                "    tracked_policy_reason: repo-local planning artifacts must never enter tracked public surface",
            ]
        )
    lines.extend(
        [
            "  .runtime-cache:",
            "    owner: repo",
            "    change_class: local-only",
            "    approval_rule: architecture-review",
            "    tracked_policy: must-remain-untracked",
            "    tracked_policy_reason: runtime artifacts must never enter tracked public surface",
        ]
    )
    (governance / "root_change_control.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_local_only_tracking_passes_for_untracked_local_only_paths(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_contracts(repo)
    plan = repo / ".agents" / "Plans" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# local only\n", encoding="utf-8")

    proc = _run([sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_local_only_tracking.py"), "--root", str(repo)], repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "local-only-tracking gate passed" in out


def test_local_only_tracking_fails_when_local_only_descendant_is_tracked(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_contracts(repo)
    plan = repo / ".agents" / "Plans" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# tracked leak\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".agents/Plans/plan.md"], check=True, text=True, capture_output=True)

    proc = _run([sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_local_only_tracking.py"), "--root", str(repo)], repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "local-only-tracking gate failed" in out
    assert ".agents/Plans/plan.md" in out


def test_local_only_tracking_fails_when_local_only_entry_lacks_explicit_tracking_policy(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_contracts(repo, include_tracked_policy=False)

    proc = _run([sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_local_only_tracking.py"), "--root", str(repo)], repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "missing tracked_policy metadata" in out


def test_repo_contract_declares_agents_as_untracked_local_only() -> None:
    allowlist = yaml.safe_load((REPO_ROOT / "contracts" / "governance" / "root_allowlist.yaml").read_text(encoding="utf-8"))
    change_control = yaml.safe_load((REPO_ROOT / "contracts" / "governance" / "root_change_control.yaml").read_text(encoding="utf-8"))

    tracking = allowlist["local_only_tracking"]
    assert tracking["mode"] == "fail-close"
    assert tracking["enforcement_target"] == "git-tracked-surface"
    assert ".agents" in tracking["entries"]
    assert ".runtime-cache" in tracking["entries"]

    agents = change_control["entries"][".agents"]
    assert agents["change_class"] == "local-only"
    assert agents["tracked_policy"] == "must-remain-untracked"
