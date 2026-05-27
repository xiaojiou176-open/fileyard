from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def test_root_public_surface_gate_rejects_internal_tooling_commands(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "governance").mkdir(parents=True)
    (repo / "apps" / "webui").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    (repo / "contracts" / "governance" / "public_surface.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "public_docs:",
                "  - README.md",
                "  - docs/usage.md",
                "public_doc_globs:",
                "  - apps/**/AGENTS.md",
                "forbidden_command_patterns:",
                '  - "(?:^|\\\\s)(?:python3?|bash)\\\\s+tooling/scripts/"',
                "package_json_script_forbidden_substrings:",
                "  - tooling/scripts/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("bash tooling/scripts/internal.sh\n", encoding="utf-8")
    (repo / "docs" / "usage.md").write_text("# usage\n", encoding="utf-8")
    (repo / "apps" / "webui" / "AGENTS.md").write_text("bash tooling/scripts/public-old.sh\n", encoding="utf-8")
    (repo / "package.json").write_text(
        json.dumps({"scripts": {"bad": "python3 tooling/scripts/internal.py"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    proc = _run(
        [sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_root_public_surface.py"), "--root", str(repo)],
        repo,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "root-public-surface gate failed" in out


def test_done_signal_claims_gate_requires_scorecard_disclaimer(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "governance").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    (repo / "tooling" / "ci").mkdir(parents=True)
    (repo / "contracts" / "governance" / "done_signal_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "canonical_delivery_gate: bash tooling/gates/quality_gate.sh",
                "governance_scorecard_gate: bash tooling/gates/verify_repo_final.sh",
                "claim_surfaces:",
                "  - path: README.md",
                "    required_snippets:",
                '      - "统一交付完成信号（只有这一条可以证明当前快照交付完成）"',
                '      - "repo 侧治理评分卡（不是交付完成证明）"',
                "  - path: docs/open_source_runbook.md",
                "    required_snippets:",
                '      - "治理评分卡（只证明 repo-side governance，不代表交付完成）"',
                '      - "唯一交付完成信号"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "统一交付完成信号（只有这一条可以证明当前快照交付完成）\n",
        encoding="utf-8",
    )
    (repo / "docs" / "open_source_runbook.md").write_text(
        "唯一交付完成信号\n",
        encoding="utf-8",
    )

    proc = _run(
        [sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_done_signal_claims.py"), "--root", str(repo)],
        repo,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "done-signal-claims gate failed" in out


def test_done_signal_policy_declares_canonical_and_host_emergency_quality_gate_receipts() -> None:
    policy = (REPO_ROOT / "contracts" / "governance" / "done_signal_policy.yaml").read_text(encoding="utf-8")

    assert "canonical_delivery_gate: bash tooling/gates/quality_gate.sh" in policy
    assert "canonical_receipt_path: .runtime-cache/logs/quality-gate/summary.json" in policy
    assert "host_emergency_gate: env FILEMAN_ALLOW_HOST_EXECUTION=1 bash tooling/gates/quality_gate.sh" in policy
    assert "host_emergency_receipt_path: .runtime-cache/logs/quality-gate/host-summary.json" in policy


def test_snapshot_scope_labels_gate_requires_declared_labels(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "docs").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    (repo / ".agents" / "Plans").mkdir(parents=True)
    (repo / "contracts" / "docs" / "snapshot_scope_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "allowed_labels:",
                "  - current-live-verified",
                "  - repo-side-only",
                "  - platform-side-not-fresh",
                "  - historical-only",
                "required_docs:",
                "  - path: docs/open_source_runbook.md",
                "    required_labels:",
                "      - repo-side-only",
                "latest_plan:",
                "  glob: .agents/Plans/*master-plan*.md",
                "  allow_missing: false",
                "  required_labels:",
                "    - current-live-verified",
                "  required_snippets:",
                '    - "Current Source Of Truth"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "docs" / "open_source_runbook.md").write_text("# Open Source Runbook\n", encoding="utf-8")
    (repo / ".agents" / "Plans" / "2026-03-17_00-00-00__repo-final-form-master-plan.md").write_text("# plan\n", encoding="utf-8")

    proc = _run(
        [sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_snapshot_scope_labels.py"), "--root", str(repo)],
        repo,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "snapshot_scope_labels: failed" in out


def test_upstream_receipts_gate_validates_failure_ownership(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "upstreams").mkdir(parents=True)
    (repo / ".runtime-cache" / "ci" / "upstream-receipts").mkdir(parents=True)
    (repo / "contracts" / "upstreams" / "compatibility_matrix.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "matrix:",
                "  - upstream_id: demo",
                "    supported_pairs:",
                '      - version: "1.0.0"',
                "        verification_suite: demo-gate",
                "        verification_mode: ci-upstream-receipt",
                "        verification_artifact: .runtime-cache/ci/upstream-receipts/demo-1-0-0.json",
                "        verification_max_age_hours: 168",
                "        rollback_baseline: restore previous demo pin",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / ".runtime-cache" / "ci" / "upstream-receipts" / "demo-1-0-0.json").write_text(
        json.dumps(
            {
                "upstream_id": "demo",
                "supported_pair": {
                    "version": "1.0.0",
                    "verification_suite": "demo-gate",
                    "verification_mode": "ci-upstream-receipt",
                    "verification_artifact": ".runtime-cache/ci/upstream-receipts/demo-1-0-0.json",
                    "verification_max_age_hours": 168,
                    "rollback_baseline": "restore previous demo pin",
                },
                "summary": {"overall_status": "passed"},
                "upstream_summary": {
                    "status": "ok",
                    "failure_ownership": {"owner": "repo", "failure_owner": "repo", "escalation": "rerun demo"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    proc = _run([sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_upstream_receipts.py"), "--root", str(repo)], repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_no_private_upstream_coupling_gate_rejects_private_imports(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "upstreams").mkdir(parents=True)
    (repo / "packages" / "demo").mkdir(parents=True)
    (repo / "apps" / "webui" / "src").mkdir(parents=True)
    (repo / "tooling" / "scripts").mkdir(parents=True)
    (repo / "contracts" / "upstreams" / "private_coupling_policy.yaml").write_text(
        (REPO_ROOT / "contracts" / "upstreams" / "private_coupling_policy.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo / "packages" / "demo" / "bad.py").write_text("from vendor._internal.api import thing\n", encoding="utf-8")
    (repo / "apps" / "webui" / "src" / "bad.ts").write_text(
        "import thing from 'react/cjs/react.production.min.js'\n",
        encoding="utf-8",
    )

    proc = _run(
        [sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_no_private_upstream_coupling.py"), "--root", str(repo)],
        repo,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "private upstream" in out


def test_governance_wiring_includes_new_dedicated_gates() -> None:
    verify = (REPO_ROOT / "tooling" / "gates" / "verify_repo_final.sh").read_text(encoding="utf-8")
    local_quality = (REPO_ROOT / "tooling" / "gates" / "local_quality_gate.sh").read_text(encoding="utf-8")
    quality = (REPO_ROOT / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")
    score = (REPO_ROOT / "tooling" / "scripts" / "score_repo_governance.py").read_text(encoding="utf-8")

    for needle in (
        "check_root_public_surface.py",
        "check_no_private_upstream_coupling.py",
        "check_done_signal_claims.py",
        "check_docs_fragment_completeness.py",
        "check_snapshot_scope_labels.py",
        "check_collaboration_surface.py",
        "check_local_only_tracking.py",
        "check_sensitive_surface.py",
        "check_feature_state_layout.py",
        "check_strategy_pack_registry.py",
        "check_watch_sources_contract.py",
    ):
        assert needle in verify
        assert needle in local_quality
        assert needle in quality
        assert needle in score

    assert "check_upstream_receipts.py" in verify
    assert "check_upstream_receipts.py" not in local_quality
    assert "check_upstream_receipts.py" in quality
    assert "check_upstream_receipts.py" in score

    assert "check_gate_log_correlation.py" in verify
    assert "check_gate_log_correlation.py" not in local_quality
    assert "check_gate_log_correlation.py" in quality
    assert "check_gate_log_correlation.py" in score
