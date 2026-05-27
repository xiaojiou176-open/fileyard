from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False, env=env)


def _write_host_capability_contracts(repo: Path) -> None:
    upstreams = repo / "contracts" / "upstreams"
    upstreams.mkdir(parents=True)
    (upstreams / "upstream_registry.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "registry:",
                "  inventory_file: contracts/upstreams/upstream_inventory.yaml",
                "  compatibility_file: contracts/upstreams/compatibility_matrix.yaml",
                "  patch_registry_file: contracts/upstreams/patch_registry.yaml",
                "  host_capability_policy_file: contracts/upstreams/host_capability_policy.yaml",
                "  license_policy_file: contracts/upstreams/license_policy.yaml",
                "  upgrade_policy_file: contracts/upstreams/upgrade_policy.yaml",
                "  failure_ownership_file: contracts/upstreams/failure_ownership.yaml",
                "required_inventory_fields:",
                "  - id",
                "  - class",
                "  - role",
                "  - source",
                "  - pin_kind",
                "  - pinned_value",
                "  - checksum_or_digest",
                "  - license",
                "  - owner",
                "  - upgrade_cadence",
                "  - verification_suite",
                "  - rollback_strategy",
                "  - failure_domain",
                "  - provenance_required",
                "  - floating_allowed",
                "class_required_fields:",
                "  system-binary:",
                "    - assurance_tier",
                "    - repo_preflight_gate",
                "    - host_management",
                "    - verification_mode",
                "    - verification_strategy",
                "    - capability_status",
                "    - install_hint",
                "    - binary_names",
                "  runtime-capability-contract:",
                "    - assurance_tier",
                "    - repo_preflight_gate",
                "    - verification_mode",
                "    - verification_strategy",
                "    - capability_status",
                "    - status_reason",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (upstreams / "patch_registry.yaml").write_text("version: 1\npatches: []\n", encoding="utf-8")
    (upstreams / "license_policy.yaml").write_text(
        "version: 1\npolicies:\n  allow_review_buckets: [mixed]\n  deny_licenses: []\n",
        encoding="utf-8",
    )
    (upstreams / "upgrade_policy.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (upstreams / "failure_ownership.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "ownership:",
                "  ffmpeg-system-binary:",
                "    owner: repo",
                "    failure_owner: repo",
                "    escalation: refresh ffmpeg declaration",
                "  document-conversion-system-binary:",
                "    owner: repo",
                "    failure_owner: repo",
                "    escalation: refresh document conversion declaration",
                "  ocr-capability-contract:",
                "    owner: repo",
                "    failure_owner: repo",
                "    escalation: keep OCR unsupported",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (upstreams / "host_capability_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "modes:",
                "  governed-host-binary-declaration:",
                (
                    "    required_inventory_fields: [assurance_tier, repo_preflight_gate, "
                    "host_management, verification_mode, verification_strategy, "
                    "capability_status, install_hint, binary_names]"
                ),
                "    required_pair_fields: [assurance_tier, repo_preflight_gate, allowed_missing_behavior, preflight_policy]",
                "  governed-unsupported-capability-declaration:",
                (
                    "    required_inventory_fields: [assurance_tier, repo_preflight_gate, "
                    "verification_mode, verification_strategy, capability_status, "
                    "status_reason]"
                ),
                "    required_pair_fields: [assurance_tier, repo_preflight_gate, allowed_missing_behavior, preflight_policy]",
                "targets:",
                "  - upstream_id: ffmpeg-system-binary",
                "    probe: ffmpeg",
                "    expected_inventory:",
                "      class: system-binary",
                "      assurance_tier: host-preflight-optional",
                "      host_management: operator-managed",
                "      verification_mode: governed-host-binary-declaration",
                "      capability_status: host-managed-optional",
                "      repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh ffmpeg-system-binary",
                "    expected_pair:",
                "      assurance_tier: host-preflight-optional",
                "      verification_mode: governed-host-binary-declaration",
                "      repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh ffmpeg-system-binary",
                "      allowed_missing_behavior: allow-and-report",
                "      preflight_policy: trusted-binary-resolution",
                "  - upstream_id: document-conversion-system-binary",
                "    probe: document-conversion",
                "    expected_inventory:",
                "      class: system-binary",
                "      assurance_tier: host-preflight-optional",
                "      host_management: operator-managed",
                "      verification_mode: governed-host-binary-declaration",
                "      capability_status: host-managed-optional",
                "      repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh document-conversion-system-binary",
                "    expected_pair:",
                "      assurance_tier: host-preflight-optional",
                "      verification_mode: governed-host-binary-declaration",
                "      repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh document-conversion-system-binary",
                "      allowed_missing_behavior: allow-and-report",
                "      preflight_policy: trusted-binary-resolution",
                "  - upstream_id: ocr-capability-contract",
                "    probe: unsupported-capability",
                "    expected_inventory:",
                "      class: runtime-capability-contract",
                "      assurance_tier: unsupported-declaration",
                "      verification_mode: governed-unsupported-capability-declaration",
                "      capability_status: unsupported",
                "      repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh ocr-capability-contract",
                "    expected_pair:",
                "      assurance_tier: unsupported-declaration",
                "      verification_mode: governed-unsupported-capability-declaration",
                "      repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh ocr-capability-contract",
                "      allowed_missing_behavior: declared-unsupported",
                "      preflight_policy: declared-unsupported",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (upstreams / "upstream_inventory.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "upstreams:",
                "  - id: ffmpeg-system-binary",
                "    class: system-binary",
                "    role: runtime",
                "    source: packages/infrastructure/audio_processing.py",
                "    pin_kind: external-state",
                "    pinned_value: host-managed-installation",
                "    checksum_or_digest: governance-declaration",
                "    license: mixed",
                "    owner: repo",
                "    upgrade_cadence: on-demand",
                "    verification_suite: upstream-governance-system-binary",
                "    rollback_strategy: restore previous ffmpeg installation",
                "    failure_domain: ci_environment",
                "    provenance_required: false",
                "    floating_allowed: false",
                "    assurance_tier: host-preflight-optional",
                "    repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh ffmpeg-system-binary",
                "    host_management: operator-managed",
                "    verification_mode: governed-host-binary-declaration",
                "    verification_strategy: detect trusted ffmpeg in PATH before optional audio segmentation",
                "    capability_status: host-managed-optional",
                "    install_hint: install ffmpeg when audio segmentation is required",
                "    binary_names: [ffmpeg]",
                "  - id: document-conversion-system-binary",
                "    class: system-binary",
                "    role: runtime",
                "    source: packages/infrastructure/document_conversion.py",
                "    pin_kind: external-state",
                "    pinned_value: host-managed-installation",
                "    checksum_or_digest: governance-declaration",
                "    license: mixed",
                "    owner: repo",
                "    upgrade_cadence: on-demand",
                "    verification_suite: upstream-governance-system-binary",
                "    rollback_strategy: restore previous libreoffice installation",
                "    failure_domain: ci_environment",
                "    provenance_required: false",
                "    floating_allowed: false",
                "    assurance_tier: host-preflight-optional",
                "    repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh document-conversion-system-binary",
                "    host_management: operator-managed",
                "    verification_mode: governed-host-binary-declaration",
                "    verification_strategy: detect trusted soffice/libreoffice/unoconv before optional document conversion",
                "    capability_status: host-managed-optional",
                "    install_hint: install LibreOffice or unoconv when conversion is required",
                "    binary_names: [soffice, libreoffice, unoconv]",
                "  - id: ocr-capability-contract",
                "    class: runtime-capability-contract",
                "    role: runtime",
                "    source: docs/usage.md",
                "    pin_kind: capability-state",
                "    pinned_value: unsupported",
                "    checksum_or_digest: governance-declaration",
                "    license: mixed",
                "    owner: repo",
                "    upgrade_cadence: on-demand",
                "    verification_suite: upstream-governance-system-binary",
                "    rollback_strategy: keep OCR disabled",
                "    failure_domain: repo_config",
                "    provenance_required: false",
                "    floating_allowed: false",
                "    assurance_tier: unsupported-declaration",
                "    repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh ocr-capability-contract",
                "    verification_mode: governed-unsupported-capability-declaration",
                "    verification_strategy: explicit governance declaration only",
                "    capability_status: unsupported",
                "    status_reason: OCR is intentionally unsupported",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (upstreams / "compatibility_matrix.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "matrix:",
                "  - upstream_id: ffmpeg-system-binary",
                "    supported_pairs:",
                "      - binary: ffmpeg",
                "        state: host-managed-optional",
                "        verification_suite: upstream-governance-system-binary",
                "        verification_mode: governed-host-binary-declaration",
                "        verification_artifact: contracts/upstreams/declarations/ffmpeg-system-binary.json",
                "        verification_max_age_hours: 8760",
                "        rollback_baseline: restore previous ffmpeg installation",
                "        assurance_tier: host-preflight-optional",
                "        repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh ffmpeg-system-binary",
                "        allowed_missing_behavior: allow-and-report",
                "        preflight_policy: trusted-binary-resolution",
                "  - upstream_id: document-conversion-system-binary",
                "    supported_pairs:",
                "      - binary_contract: soffice-or-libreoffice-or-unoconv",
                "        state: host-managed-optional",
                "        verification_suite: upstream-governance-system-binary",
                "        verification_mode: governed-host-binary-declaration",
                "        verification_artifact: contracts/upstreams/declarations/document-conversion-system-binary.json",
                "        verification_max_age_hours: 8760",
                "        rollback_baseline: restore previous libreoffice installation",
                "        assurance_tier: host-preflight-optional",
                "        repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh document-conversion-system-binary",
                "        allowed_missing_behavior: allow-and-report",
                "        preflight_policy: trusted-binary-resolution",
                "  - upstream_id: ocr-capability-contract",
                "    supported_pairs:",
                "      - capability: ocr",
                "        state: unsupported",
                "        verification_suite: upstream-governance-system-binary",
                "        verification_mode: governed-unsupported-capability-declaration",
                "        verification_artifact: contracts/upstreams/declarations/ocr-capability-contract.json",
                "        verification_max_age_hours: 8760",
                "        rollback_baseline: keep OCR disabled",
                "        assurance_tier: unsupported-declaration",
                "        repo_preflight_gate: bash tooling/gates/host_capability_preflight.sh ocr-capability-contract",
                "        allowed_missing_behavior: declared-unsupported",
                "        preflight_policy: declared-unsupported",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_check_upstream_drift_enforces_system_binary_class_fields(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_host_capability_contracts(repo)
    inventory_path = repo / "contracts" / "upstreams" / "upstream_inventory.yaml"
    inventory_text = inventory_path.read_text(encoding="utf-8").replace("    assurance_tier: host-preflight-optional\n", "", 1)
    inventory_path.write_text(inventory_text, encoding="utf-8")

    proc = _run([sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_upstream_drift.py"), "--root", str(repo)], repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "missing system-binary fields: assurance_tier" in out


def test_check_upstream_compat_matrix_requires_host_capability_pair_fields(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_host_capability_contracts(repo)
    matrix_path = repo / "contracts" / "upstreams" / "compatibility_matrix.yaml"
    matrix_text = matrix_path.read_text(encoding="utf-8").replace("        preflight_policy: trusted-binary-resolution\n", "", 1)
    matrix_path.write_text(matrix_text, encoding="utf-8")

    proc = _run(
        [sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_upstream_compat_matrix.py"), "--root", str(repo)],
        repo,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "missing host-capability fields for governed-host-binary-declaration: preflight_policy" in out


def test_host_capability_preflight_reports_detected_and_unsupported_states(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_host_capability_contracts(repo)
    ffmpeg_bin = tmp_path / "bin" / "ffmpeg"
    ffmpeg_bin.parent.mkdir(parents=True)
    ffmpeg_bin.write_text("x", encoding="utf-8")
    ffmpeg_bin.chmod(0o755)
    soffice_bin = tmp_path / "bin" / "soffice"
    soffice_bin.write_text("x", encoding="utf-8")
    soffice_bin.chmod(0o755)
    summary_path = tmp_path / "summary.json"

    env = os.environ.copy()
    env["FILEMAN_ENABLE_TEST_HOOKS"] = "1"
    env["PATH"] = str(ffmpeg_bin.parent) + os.pathsep + env.get("PATH", "")

    proc = _run(
        [
            "bash",
            str(REPO_ROOT / "tooling" / "gates" / "host_capability_preflight.sh"),
            "--root",
            str(repo),
            "--json-out",
            str(summary_path),
        ],
        repo,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    statuses = {item["upstream_id"]: item["probe_result"]["status"] for item in summary["targets"]}
    assert statuses["ffmpeg-system-binary"] == "detected"
    assert statuses["document-conversion-system-binary"] == "detected"
    assert statuses["ocr-capability-contract"] == "unsupported-declared"
