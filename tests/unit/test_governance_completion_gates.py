from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def test_root_change_control_gate_requires_metadata_for_every_allowlisted_entry(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "governance").mkdir(parents=True)
    (repo / "contracts" / "governance" / "root_allowlist.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "canonical_tracked_entries:",
                "  - README.md",
                "local_only_entries:",
                "  - .runtime-cache",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "root_change_control.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "entries:",
                "  README.md:",
                "    owner: repo",
                "    change_class: public-doc",
                "    approval_rule: architecture-review",
                "  .runtime-cache:",
                "    owner: repo",
                "    change_class: local-only",
                "    approval_rule: architecture-review",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    proc = _run([sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_root_change_control.py"), "--root", str(repo)], repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_root_change_control_gate_fails_when_allowlist_entry_has_no_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "governance").mkdir(parents=True)
    (repo / "contracts" / "governance" / "root_allowlist.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "canonical_tracked_entries:",
                "  - README.md",
                "  - docs",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "root_change_control.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "entries:",
                "  README.md:",
                "    owner: repo",
                "    change_class: public-doc",
                "    approval_rule: architecture-review",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    proc = _run([sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_root_change_control.py"), "--root", str(repo)], repo)
    assert proc.returncode == 1
    assert "missing change-control metadata" in (proc.stdout + proc.stderr)


def test_cold_start_public_wrapper_uses_dedicated_gate() -> None:
    package_json = (REPO_ROOT / "package.json").read_text(encoding="utf-8")
    assert '"cold-cache:check": "bash tooling/gates/check_cold_start_rebuild.sh"' in package_json


def test_runtime_reset_script_requires_explicit_confirmation_flag_in_package_script() -> None:
    package_json = (REPO_ROOT / "package.json").read_text(encoding="utf-8")
    assert '"runtime:reset": "bash tooling/runtime/runtime_reset.sh --confirm-workspace-reset"' in package_json


def test_pip_audit_allowlist_scopes_pygments_cve_to_dev_lock_only() -> None:
    allowlist = yaml.safe_load((REPO_ROOT / "contracts" / "governance" / "pip_audit_allowlist.yaml").read_text(encoding="utf-8"))
    assert allowlist["version"] == 1

    entries = allowlist["entries"]
    entry = next(item for item in entries if item["id"] == "CVE-2026-4539")

    assert entry["package"] == "pygments"
    assert entry["version"] == "2.19.2"
    assert entry["scope"] == "dev-lock-only"
    assert entry["status"] == "active"
    assert "No patched Pygments release is available on PyPI" in entry["rationale"]


def test_governance_wiring_includes_cold_start_and_root_change_control_gates() -> None:
    verify = (REPO_ROOT / "tooling" / "gates" / "verify_repo_final.sh").read_text(encoding="utf-8")
    local_quality = (REPO_ROOT / "tooling" / "gates" / "local_quality_gate.sh").read_text(encoding="utf-8")
    quality = (REPO_ROOT / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")
    score = (REPO_ROOT / "tooling" / "scripts" / "score_repo_governance.py").read_text(encoding="utf-8")

    assert "check_cold_start_rebuild.py" in verify
    assert "check_root_change_control.py" in verify
    assert "check_collaboration_surface.py" in verify
    assert "check_runtime_language_boundary.py" in verify
    assert "check_public_artifact_safety.py" in verify
    assert "check_sensitive_surface.py" in verify
    assert "check_local_only_tracking.py" in verify
    assert "check_feature_state_layout.py" in verify
    assert "check_strategy_pack_registry.py" in verify
    assert "check_watch_sources_contract.py" in verify
    assert "check_cold_start_rebuild.py" in score
    assert "check_root_change_control.py" in score
    assert "check_collaboration_surface.py" in score
    assert "check_runtime_language_boundary.py" in score
    assert "check_public_artifact_safety.py" in score
    assert "check_sensitive_surface.py" in score
    assert "check_local_only_tracking.py" in score
    assert "check_feature_state_layout.py" in score
    assert "check_strategy_pack_registry.py" in score
    assert "check_watch_sources_contract.py" in score
    assert "check_root_change_control.py" in local_quality
    assert "check_root_change_control.py" in quality
    assert "check_collaboration_surface.py" in local_quality
    assert "check_runtime_language_boundary.py" in local_quality
    assert "check_public_artifact_safety.py" in local_quality
    assert "check_sensitive_surface.py" in local_quality
    assert "check_collaboration_surface.py" in quality
    assert "check_runtime_language_boundary.py" in quality
    assert "check_public_artifact_safety.py" in quality
    assert "check_sensitive_surface.py" in quality
    assert "check_local_only_tracking.py" in local_quality
    assert "check_local_only_tracking.py" in quality
    assert "check_feature_state_layout.py" in local_quality
    assert "check_feature_state_layout.py" in quality
    assert "check_mcp_surface.py" in verify
    assert "check_mcp_surface.py" in local_quality
    assert "check_mcp_surface.py" in quality
    assert "check_strategy_pack_registry.py" in local_quality
    assert "check_strategy_pack_registry.py" in quality
    assert "check_watch_sources_contract.py" in local_quality
    assert "check_watch_sources_contract.py" in quality
    assert "check_runtime_language_boundary.py" in quality
    assert "check_done_signal_claims.py" in verify
    assert "check_done_signal_claims.py" in score
    assert "check_done_signal_claims.py" in local_quality
    assert "check_done_signal_claims.py" in quality
    assert "check_docs_fragment_completeness.py" in verify
    assert "check_docs_truth_routes.py" in verify
    assert "check_docs_fragment_completeness.py" in score
    assert "check_docs_truth_routes.py" in score
    assert "check_docs_fragment_completeness.py" in local_quality
    assert "check_docs_truth_routes.py" in local_quality
    assert "check_docs_fragment_completeness.py" in quality
    assert "check_docs_truth_routes.py" in quality
    assert "check_snapshot_scope_labels.py" in verify
    assert "check_snapshot_scope_labels.py" in score
    assert "check_snapshot_scope_labels.py" in local_quality
    assert "check_snapshot_scope_labels.py" in quality
    assert "check_gate_log_correlation.py" in verify
    assert "check_gate_log_correlation.py" in score
    assert "check_gate_log_correlation.py" not in local_quality
    assert "check_gate_log_correlation.py" in quality
    assert "check_positioning_claims.py" in verify
    assert "check_positioning_claims.py" in score
    assert "check_positioning_claims.py" in local_quality
    assert "check_positioning_claims.py" in quality
    assert "check_hotspot_budget.py" in verify
    assert "check_hotspot_budget.py" in score
    assert "check_hotspot_budget.py" in local_quality
    assert "check_hotspot_budget.py" in quality
    assert "check_upstream_host_capabilities.py" in verify
    assert "check_upstream_host_capabilities.py" in score
    assert "check_upstream_host_capabilities.py" in local_quality
    assert "check_upstream_host_capabilities.py" in quality
    assert '--gate-run-id "$GATE_RUN_ID" --gate-name "$GATE_NAME"' in quality
    assert '--gate-run-id "$VERIFY_GATE_RUN_ID" --gate-name "verify-repo-final"' in verify


def test_governance_runtime_hygiene_uses_governed_python_entrypoint() -> None:
    verify = (REPO_ROOT / "tooling" / "gates" / "verify_repo_final.sh").read_text(encoding="utf-8")
    lib_config = (REPO_ROOT / "tooling" / "scripts" / "lib_config.sh").read_text(encoding="utf-8")

    assert "governance_python()" in lib_config
    assert 'PYTHONPATH="${governed_pythonpath}:${PYTHONPATH}" python3 "$@"' in lib_config
    assert 'governance_python "$REPO_ROOT" "$ROOT/scripts/check_docs_render_state.py" --root "$REPO_ROOT"' in verify
