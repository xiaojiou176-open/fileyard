from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def _write_policy(repo: Path) -> None:
    (repo / "contracts" / "governance").mkdir(parents=True, exist_ok=True)
    (repo / "contracts" / "governance" / "public_artifact_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "provenance_contract: contracts/governance/public_asset_provenance.yaml",
                "require_declared_entries_cover_all_files: true",
                "audited_roots:",
                "  - path: apps/webui/public",
                "    expected_kinds:",
                "      - public-brand-asset",
                "    expected_statuses:",
                "      - repository-authored",
                "    expected_licenses:",
                "      - MIT",
                "    allowed_extensions:",
                "      - .svg",
                "  - path: tests/fixtures/golden_input",
                "    expected_kinds:",
                "      - public-test-fixture",
                "    expected_statuses:",
                "      - repository-maintained-synthetic",
                "    expected_licenses:",
                "      - MIT",
                "    allowed_extensions:",
                "      - .pdf",
                "      - .png",
                "global_forbidden_extensions:",
                "  - .har",
                "  - .log",
                "  - .sql",
                "text_scan:",
                "  enabled: true",
                "  extensions:",
                "    - .svg",
                "  forbidden_regex:",
                '    - "(?i)authorization\\\\s*:"',
                "documentation_surfaces:",
                "  - path: docs/open_source_runbook.md",
                "    required_substrings:",
                '      - "bash tooling/gates/public_artifact_audit.sh"',
                "  - path: THIRD_PARTY_NOTICES.md",
                "    required_substrings:",
                '      - "contracts/governance/public_asset_provenance.yaml"',
                '      - "bash tooling/gates/public_artifact_audit.sh"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_public_artifact_audit_fails_when_audited_file_is_undeclared(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "apps" / "webui" / "public").mkdir(parents=True)
    (repo / "tests" / "fixtures" / "golden_input").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    _write_policy(repo)
    (repo / "apps" / "webui" / "public" / "fileorganize-mark.svg").write_text("<svg/>", encoding="utf-8")
    (repo / "tests" / "fixtures" / "golden_input" / "doc.pdf").write_text("hello", encoding="utf-8")
    (repo / "contracts" / "governance" / "public_asset_provenance.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "assets:",
                "  - path: apps/webui/public/fileorganize-mark.svg",
                "    kind: public-brand-asset",
                "    status: repository-authored",
                "    license: MIT",
                "    sha256: 6b3ec4dca2566cd9d2f0ae492e4d7af90bfc15613910e6e0bd43f5b565efce3a",
                "    file_size_bytes: 6",
                "    notes: repo asset",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "docs" / "open_source_runbook.md").write_text("bash tooling/gates/public_artifact_audit.sh\n", encoding="utf-8")
    (repo / "THIRD_PARTY_NOTICES.md").write_text(
        "contracts/governance/public_asset_provenance.yaml\nbash tooling/gates/public_artifact_audit.sh\n",
        encoding="utf-8",
    )

    proc = _run(
        [sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_public_artifact_safety.py"), "--root", str(repo)],
        repo,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "public-artifact-safety: failed" in out
    assert "tests/fixtures/golden_input/doc.pdf: file exists under audited root but is not declared" in out


def test_public_artifact_audit_fails_on_forbidden_extension_or_secret_like_content(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "apps" / "webui" / "public").mkdir(parents=True)
    (repo / "tests" / "fixtures" / "golden_input").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    _write_policy(repo)
    (repo / "apps" / "webui" / "public" / "fileorganize-mark.svg").write_text("Authorization: Bearer token\n", encoding="utf-8")
    (repo / "tests" / "fixtures" / "golden_input" / "capture.har").write_text("{}", encoding="utf-8")
    (repo / "contracts" / "governance" / "public_asset_provenance.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "assets:",
                "  - path: apps/webui/public/fileorganize-mark.svg",
                "    kind: public-brand-asset",
                "    status: repository-authored",
                "    license: MIT",
                "    sha256: 13d3f906c6e74ffa917389bc4fd991f16d6f94a6f865dde2bca54fba14fa4f96",
                "    file_size_bytes: 28",
                "    notes: repo asset",
                "  - path: tests/fixtures/golden_input/capture.har",
                "    kind: public-test-fixture",
                "    status: repository-maintained-synthetic",
                "    license: MIT",
                "    sha256: 44136fa355b3678a1146ad16f7e8649e94fb4fc21fdbd2f3c64e12a5a244260f",
                "    file_size_bytes: 2",
                "    notes: unsafe fixture",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "docs" / "open_source_runbook.md").write_text("bash tooling/gates/public_artifact_audit.sh\n", encoding="utf-8")
    (repo / "THIRD_PARTY_NOTICES.md").write_text(
        "contracts/governance/public_asset_provenance.yaml\nbash tooling/gates/public_artifact_audit.sh\n",
        encoding="utf-8",
    )

    proc = _run(
        [sys.executable, str(REPO_ROOT / "tooling" / "scripts" / "check_public_artifact_safety.py"), "--root", str(repo)],
        repo,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "forbidden public artifact extension .har" in out
    assert "forbidden public artifact content matched" in out
