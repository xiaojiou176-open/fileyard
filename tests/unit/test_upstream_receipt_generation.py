from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tooling.scripts.generate_ci_evidence_bundle import _write_upstream_receipts


def test_write_upstream_receipts_generates_per_pair_artifacts(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "contracts" / "upstreams"
    contracts_dir.mkdir(parents=True)
    (contracts_dir / "upstream_inventory.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "upstreams:",
                "  - id: demo-upstream",
                "    class: demo-class",
                "    role: build",
                "    pin_kind: version",
                "    pinned_value: 1.2.3",
                "    verification_suite: demo-gate",
                "    failure_domain: upstream_demo",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (contracts_dir / "compatibility_matrix.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "matrix:",
                "  - upstream_id: demo-upstream",
                "    supported_pairs:",
                '      - version: "1.2.3"',
                "        verification_suite: demo-gate",
                "        verification_mode: ci-upstream-receipt",
                "        verification_artifact: .runtime-cache/ci/upstream-receipts/demo-upstream-1-2-3.json",
                "        verification_max_age_hours: 168",
                "        rollback_baseline: restore previous demo pin",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    bundle = {
        "summary": {"overall_status": "passed"},
        "context": {"event": "local", "run_id": "demo"},
        "failure_summary": {"overall_status": "passed"},
        "truth": {
            "truth_class": "derived-report",
            "source_run_type": "local",
            "authoritative_terminal_receipt": {
                "truth_class": "authoritative-terminal-receipt",
                "path": ".runtime-cache/logs/quality-gate/summary.json",
            },
            "remote_traceability": {"status": "local-only", "has_github_run_id": False},
        },
    }
    bundle_output = tmp_path / ".runtime-cache" / "ci" / "evidence-bundle.json"
    bundle_output.parent.mkdir(parents=True, exist_ok=True)
    bundle_output.write_text("{}", encoding="utf-8")

    written = _write_upstream_receipts(tmp_path, bundle, bundle_output)

    receipt_path = tmp_path / ".runtime-cache" / "ci" / "upstream-receipts" / "demo-upstream-1-2-3.json"
    assert written == [str(receipt_path)]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["upstream_id"] == "demo-upstream"
    assert receipt["supported_pair"]["version"] == "1.2.3"
    assert receipt["summary"]["overall_status"] == "passed"
    assert receipt["source_bundle_truth"]["truth_class"] == "derived-report"
    assert receipt["source_bundle_truth"]["source_run_type"] == "local"
    assert receipt["source_bundle_truth"]["remote_traceability"]["status"] == "local-only"
    assert receipt["upstream_summary"]["status"] == "ok"


def test_refresh_upstream_receipts_imports_from_existing_bundle(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "contracts" / "upstreams"
    contracts_dir.mkdir(parents=True)
    (contracts_dir / "upstream_inventory.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "upstreams:",
                "  - id: demo-upstream",
                "    class: demo-class",
                "    role: build",
                "    pin_kind: version",
                "    pinned_value: 1.2.3",
                "    verification_suite: demo-gate",
                "    failure_domain: upstream_demo",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (contracts_dir / "failure_ownership.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "ownership:",
                "  demo-upstream:",
                "    owner: repo",
                "    failure_owner: repo",
                "    escalation: rerun demo gate",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (contracts_dir / "compatibility_matrix.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "matrix:",
                "  - upstream_id: demo-upstream",
                "    supported_pairs:",
                '      - version: "1.2.3"',
                "        verification_suite: demo-gate",
                "        verification_mode: ci-upstream-receipt",
                "        verification_artifact: .runtime-cache/ci/upstream-receipts/demo-upstream-1-2-3.json",
                "        verification_max_age_hours: 168",
                "        rollback_baseline: restore previous demo pin",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    bundle_path = tmp_path / ".runtime-cache" / "ci" / "evidence-bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(
            {
                "summary": {"overall_status": "passed", "gate_overall": "passed"},
                "upstream_summary": {"status": "ok"},
                "context": {"event": "local", "run_id": "demo"},
                "failure_summary": {"overall_status": "passed"},
                "truth": {
                    "truth_class": "derived-report",
                    "source_run_type": "local",
                    "authoritative_terminal_receipt": {
                        "truth_class": "authoritative-terminal-receipt",
                        "path": ".runtime-cache/logs/quality-gate/summary.json",
                    },
                    "remote_traceability": {"status": "local-only", "has_github_run_id": False},
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "tooling" / "scripts" / "refresh_upstream_receipts.py"),
            "--root",
            str(tmp_path),
            "--bundle",
            str(bundle_path),
        ],
        cwd=str(tmp_path),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    receipt_path = tmp_path / ".runtime-cache" / "ci" / "upstream-receipts" / "demo-upstream-1-2-3.json"
    summary_path = tmp_path / ".runtime-cache" / "ci" / "upstream-receipts" / "summary.json"
    assert receipt_path.exists()
    assert summary_path.exists()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["source_bundle_truth"]["truth_class"] == "derived-report"
    assert receipt["source_bundle_truth"]["authoritative_terminal_receipt"]["path"] == ".runtime-cache/logs/quality-gate/summary.json"
