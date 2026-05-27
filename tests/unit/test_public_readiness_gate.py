from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MINIMAL_SECURITY_TEXT = (
    "\n".join(
        [
            "# Security Policy",
            "GitHub Private Vulnerability Reporting is the primary private reporting channel for this repository.",
            "No separate fallback private email is currently configured for this repository.",
            "Do not report security vulnerabilities in public GitHub issues.",
        ]
    )
    + "\n"
)


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False, env=env)


def _write_minimal_policy(repo: Path) -> None:
    (repo / "contracts" / "governance").mkdir(parents=True, exist_ok=True)
    (repo / "contracts" / "governance" / "public_readiness_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "default_branch: main",
                "required_repo_surface_files:",
                "  - LICENSE",
                "  - SECURITY.md",
                "  - contracts/governance/public_asset_provenance.yaml",
                "  - docs/open_source_runbook.md",
                "required_package_scripts:",
                "  - public:readiness",
                "required_runbook_snippets:",
                '  - "bash tooling/gates/public_readiness_gate.sh repo"',
                '  - "bash tooling/gates/public_readiness_gate.sh release"',
                "required_asset_provenance_entries:",
                "  - tests/fixtures/golden_input/doc.pdf",
                "release_mode:",
                "  require_tracked_files: true",
                "  require_public_repo: true",
                "  require_pvr: true",
                "  require_branch_protection: true",
                "  require_zero_code_scanning_alerts: true",
                "  require_zero_secret_scanning_alerts: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "collaboration_surface_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "default_language: en",
                "fail_close: true",
                "global_forbidden_regex:",
                '  - "[\\\\u4e00-\\\\u9fff]"',
                "targets:",
                "  - path: SECURITY.md",
                "    required_substrings:",
                '      - "# Security Policy"',
                '      - "GitHub Private Vulnerability Reporting is the primary private reporting"',
                '      - "No separate fallback private email is currently configured"',
                '      - "Do not report security vulnerabilities in public GitHub issues"',
                "    forbidden_substrings:",
                '      - "placeholder private contact channel"',
                "  - path: SUPPORT.md",
                "    required_substrings:",
                '      - "# Support"',
                "  - path: CONTRIBUTING.md",
                "    required_substrings:",
                '      - "# Contributing"',
                "  - path: CODE_OF_CONDUCT.md",
                "    required_substrings:",
                '      - "# Code of Conduct"',
                "  - path: .github/ISSUE_TEMPLATE/bug_report.yml",
                "    required_substrings:",
                '      - "Please read `SUPPORT.md` first"',
                "  - path: .github/ISSUE_TEMPLATE/documentation.yml",
                "    required_substrings:",
                '      - "Use this template for documentation drift"',
                "  - path: .github/PULL_REQUEST_TEMPLATE.md",
                "    required_substrings:",
                '      - "## Collaboration Surface"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "root_allowlist.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "canonical_tracked_entries:",
                "  - LICENSE",
                "  - SECURITY.md",
                "  - SUPPORT.md",
                "  - CONTRIBUTING.md",
                "  - CODE_OF_CONDUCT.md",
                "  - .github",
                "  - contracts",
                "  - docs",
                "  - package.json",
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
                "  .agents:",
                "    owner: repo",
                "    change_class: local-only",
                "    approval_rule: architecture-review",
                "    tracked_policy: must-remain-untracked",
                "    tracked_policy_reason: repo-local execution plans must stay out of git tracked public surface",
                "  .runtime-cache:",
                "    owner: repo",
                "    change_class: local-only",
                "    approval_rule: architecture-review",
                "    tracked_policy: must-remain-untracked",
                "    tracked_policy_reason: runtime caches must stay out of git tracked public surface",
                "  LICENSE:",
                "    owner: repo",
                "    change_class: legal",
                "    approval_rule: architecture-review",
                "  SECURITY.md:",
                "    owner: repo",
                "    change_class: security",
                "    approval_rule: architecture-review",
                "  SUPPORT.md:",
                "    owner: repo",
                "    change_class: public-doc",
                "    approval_rule: architecture-review",
                "  CONTRIBUTING.md:",
                "    owner: repo",
                "    change_class: public-doc",
                "    approval_rule: architecture-review",
                "  CODE_OF_CONDUCT.md:",
                "    owner: repo",
                "    change_class: public-doc",
                "    approval_rule: architecture-review",
                "  .github:",
                "    owner: repo",
                "    change_class: platform",
                "    approval_rule: architecture-review",
                "  contracts:",
                "    owner: repo",
                "    change_class: canonical-root",
                "    approval_rule: architecture-review",
                "  docs:",
                "    owner: repo",
                "    change_class: canonical-root",
                "    approval_rule: architecture-review",
                "  package.json:",
                "    owner: repo",
                "    change_class: public-entrypoint",
                "    approval_rule: architecture-review",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_public_readiness_gate_repo_mode_passes_with_repo_surface_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "contracts" / "governance").mkdir(parents=True, exist_ok=True)
    (repo / "tests" / "fixtures" / "golden_input").mkdir(parents=True)
    _write_minimal_policy(repo)
    (repo / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (repo / "SECURITY.md").write_text(MINIMAL_SECURITY_TEXT, encoding="utf-8")
    (repo / "SUPPORT.md").write_text("# Support\n", encoding="utf-8")
    (repo / "CONTRIBUTING.md").write_text("# Contributing\n", encoding="utf-8")
    (repo / "CODE_OF_CONDUCT.md").write_text("# Code of Conduct\n", encoding="utf-8")
    (repo / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True, exist_ok=True)
    (repo / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").write_text(
        "Please read `SUPPORT.md` first\n",
        encoding="utf-8",
    )
    (repo / ".github" / "ISSUE_TEMPLATE" / "documentation.yml").write_text(
        "Use this template for documentation drift\n",
        encoding="utf-8",
    )
    (repo / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text(
        "## Collaboration Surface\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "public_asset_provenance.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "assets:",
                "  - path: tests/fixtures/golden_input/doc.pdf",
                "    kind: public-test-fixture",
                "    status: repository-maintained-synthetic",
                "    license: MIT",
                "    sha256: 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                "    file_size_bytes: 5",
                "    notes: synthetic fixture",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "tests" / "fixtures" / "golden_input" / "doc.pdf").write_text("hello", encoding="utf-8")
    (repo / "docs" / "open_source_runbook.md").write_text(
        "bash tooling/gates/public_readiness_gate.sh repo\nbash tooling/gates/public_readiness_gate.sh release\n",
        encoding="utf-8",
    )
    (repo / "package.json").write_text(
        json.dumps({"scripts": {"public:readiness": "bash tooling/gates/public_readiness_gate.sh release"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    proc = _run(["bash", str(REPO_ROOT / "tooling" / "gates" / "public_readiness_gate.sh"), "repo"], repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "public-readiness-repo-surface: passed" in (proc.stdout + proc.stderr)


def test_public_readiness_gate_release_mode_requires_tracked_files_and_platform_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "contracts" / "governance").mkdir(parents=True, exist_ok=True)
    (repo / "tests" / "fixtures" / "golden_input").mkdir(parents=True)
    _write_minimal_policy(repo)
    (repo / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (repo / "SECURITY.md").write_text(MINIMAL_SECURITY_TEXT, encoding="utf-8")
    (repo / "SUPPORT.md").write_text("# Support\n", encoding="utf-8")
    (repo / "CONTRIBUTING.md").write_text("# Contributing\n", encoding="utf-8")
    (repo / "CODE_OF_CONDUCT.md").write_text("# Code of Conduct\n", encoding="utf-8")
    (repo / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True, exist_ok=True)
    (repo / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").write_text(
        "Please read `SUPPORT.md` first\n",
        encoding="utf-8",
    )
    (repo / ".github" / "ISSUE_TEMPLATE" / "documentation.yml").write_text(
        "Use this template for documentation drift\n",
        encoding="utf-8",
    )
    (repo / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text(
        "## Collaboration Surface\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "public_asset_provenance.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "assets:",
                "  - path: tests/fixtures/golden_input/doc.pdf",
                "    kind: public-test-fixture",
                "    status: repository-maintained-synthetic",
                "    license: MIT",
                "    sha256: 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                "    file_size_bytes: 5",
                "    notes: synthetic fixture",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "tests" / "fixtures" / "golden_input" / "doc.pdf").write_text("hello", encoding="utf-8")
    (repo / "docs" / "open_source_runbook.md").write_text(
        "bash tooling/gates/public_readiness_gate.sh repo\nbash tooling/gates/public_readiness_gate.sh release\n",
        encoding="utf-8",
    )
    (repo / "package.json").write_text(
        json.dumps({"scripts": {"public:readiness": "bash tooling/gates/public_readiness_gate.sh release"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    proc = _run(["bash", str(REPO_ROOT / "tooling" / "gates" / "public_readiness_gate.sh"), "release"], repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert (
        "release mode requires tracked public surface file" in out
        or "GitHub repo metadata unavailable" in out
        or "release mode requires a public repository" in out
    )


def test_check_public_platform_state_reports_query_blocked_when_viewer_permission_is_read(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (repo / "contracts" / "governance").mkdir(parents=True, exist_ok=True)
    (repo / "contracts" / "governance" / "public_readiness_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "default_branch: main",
                "release_mode:",
                "  require_public_repo: true",
                "  require_pvr: true",
                "  require_branch_protection: true",
                "  require_zero_code_scanning_alerts: true",
                "  require_zero_secret_scanning_alerts: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gh = bin_dir / "gh"
    gh.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "repo" ] && [ "$2" = "view" ]; then',
                (
                    "  printf '%s\\n' "
                    '\'{"nameWithOwner":"demo/repo","isPrivate":false,"viewerPermission":"READ",'
                    '"defaultBranchRef":{"name":"main"}}\''
                ),
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/private-vulnerability-reporting" ]; then',
                "  printf '%s\\n' '{\"enabled\":true}'",
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/branches/main/protection" ]; then',
                '  echo \'{"message":"Not Found"}\' >&2',
                "  exit 1",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/code-scanning/alerts?state=open&per_page=100" ]; then',
                "  printf '%s\\n' '[]'",
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/secret-scanning/alerts?state=open&per_page=100" ]; then',
                "  printf '%s\\n' '[]'",
                "  exit 0",
                "fi",
                'echo "unsupported gh args: $*" >&2',
                "exit 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

    proc = _run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_public_platform_state.py"),
            "--root",
            str(repo),
            "--mode",
            "release",
        ],
        repo,
        env=env,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "current viewer permission is READ" in out


def test_check_remote_required_checks_reports_query_blocked_when_viewer_permission_is_read(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (repo / "contracts" / "governance").mkdir(parents=True)
    (repo / "contracts" / "governance" / "required_checks_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "workflow_file: .github/workflows/ci.yml",
                "branch_protection_target: main",
                "required_checks:",
                "  - job_id: quality-gate-full",
                "    blocking_level: required",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "public_readiness_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "default_branch: main",
                "release_mode:",
                "  require_public_repo: true",
                "  require_pvr: true",
                "  require_branch_protection: true",
                "  require_zero_code_scanning_alerts: true",
                "  require_zero_secret_scanning_alerts: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gh = bin_dir / "gh"
    gh.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "repo" ] && [ "$2" = "view" ]; then',
                (
                    "  printf '%s\\n' "
                    '\'{"nameWithOwner":"demo/repo","isPrivate":false,"viewerPermission":"READ",'
                    '"defaultBranchRef":{"name":"main"}}\''
                ),
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/private-vulnerability-reporting" ]; then',
                "  printf '%s\\n' '{\"enabled\":true}'",
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/branches/main/protection" ]; then',
                '  echo \'{"message":"Not Found"}\' >&2',
                "  exit 1",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/code-scanning/alerts?state=open&per_page=100" ]; then',
                "  printf '%s\\n' '[]'",
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/secret-scanning/alerts?state=open&per_page=100" ]; then',
                "  printf '%s\\n' '[]'",
                "  exit 0",
                "fi",
                'echo "unsupported gh args: $*" >&2',
                "exit 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

    proc = _run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_remote_required_checks.py"),
            "--root",
            str(repo),
        ],
        repo,
        env=env,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "viewer permission READ" in out


def test_check_public_platform_state_fails_when_open_security_alerts_exist(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (repo / "contracts" / "governance").mkdir(parents=True, exist_ok=True)
    (repo / "contracts" / "governance" / "public_readiness_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "default_branch: main",
                "release_mode:",
                "  require_public_repo: true",
                "  require_pvr: true",
                "  require_branch_protection: true",
                "  require_zero_code_scanning_alerts: true",
                "  require_zero_secret_scanning_alerts: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gh = bin_dir / "gh"
    gh.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "repo" ] && [ "$2" = "view" ]; then',
                (
                    "  printf '%s\\n' "
                    '\'{"nameWithOwner":"demo/repo","isPrivate":false,"viewerPermission":"ADMIN",'
                    '"defaultBranchRef":{"name":"main"}}\''
                ),
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/private-vulnerability-reporting" ]; then',
                "  printf '%s\\n' '{\"enabled\":true}'",
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/branches/main/protection" ]; then',
                '  printf \'%s\\n\' \'{"required_status_checks":{"contexts":["quality-gate-full"]}}\'',
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/code-scanning/alerts?state=open&per_page=100" ]; then',
                "  printf '%s\\n' '[{\"number\":1}]'",
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/secret-scanning/alerts?state=open&per_page=100" ]; then',
                "  printf '%s\\n' '[{\"number\":2}]'",
                "  exit 0",
                "fi",
                'echo "unsupported gh args: $*" >&2',
                "exit 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

    proc = _run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_public_platform_state.py"),
            "--root",
            str(repo),
            "--mode",
            "release",
        ],
        repo,
        env=env,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "zero open GitHub code scanning alerts" in out
    assert "zero open GitHub secret scanning alerts" in out


def test_check_public_platform_state_accepts_explicit_code_scanning_allowlist(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (repo / "contracts" / "governance").mkdir(parents=True, exist_ok=True)
    (repo / "contracts" / "governance" / "public_readiness_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "default_branch: main",
                "accepted_code_scanning_rules_contract: contracts/governance/code_scanning_alert_allowlist.yaml",
                "release_mode:",
                "  require_public_repo: true",
                "  require_pvr: true",
                "  require_branch_protection: true",
                "  require_zero_code_scanning_alerts: true",
                "  require_zero_secret_scanning_alerts: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "code_scanning_alert_allowlist.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "status: active",
                "accepted_rule_ids:",
                "  - CIIBestPracticesID",
                "  - MaintainedID",
                "  - CodeReviewID",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gh = bin_dir / "gh"
    gh.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "repo" ] && [ "$2" = "view" ]; then',
                (
                    "  printf '%s\\n' "
                    '\'{"nameWithOwner":"demo/repo","isPrivate":false,"viewerPermission":"ADMIN",'
                    '"defaultBranchRef":{"name":"main"}}\''
                ),
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/private-vulnerability-reporting" ]; then',
                "  printf '%s\\n' '{\"enabled\":true}'",
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/branches/main/protection" ]; then',
                '  printf \'%s\\n\' \'{"required_status_checks":{"contexts":["quality-gate-full"]}}\'',
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/code-scanning/alerts?state=open&per_page=100" ]; then',
                (
                    "  printf '%s\\n' "
                    '\'[{"rule":{"id":"CIIBestPracticesID"}},{"rule":{"id":"MaintainedID"}},{"rule":{"id":"CodeReviewID"}}]\''
                ),
                "  exit 0",
                "fi",
                'if [ "$1" = "api" ] && [ "$2" = "repos/demo/repo/secret-scanning/alerts?state=open&per_page=100" ]; then',
                "  printf '%s\\n' '[]'",
                "  exit 0",
                "fi",
                'echo "unsupported gh args: $*" >&2',
                "exit 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

    proc = _run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_public_platform_state.py"),
            "--root",
            str(repo),
            "--mode",
            "release",
        ],
        repo,
        env=env,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "public-platform-state: passed" in out


def test_public_readiness_gate_honors_explicit_target_root_from_outside_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "contracts" / "governance").mkdir(parents=True, exist_ok=True)
    (repo / "tests" / "fixtures" / "golden_input").mkdir(parents=True)
    _write_minimal_policy(repo)
    (repo / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (repo / "SECURITY.md").write_text(MINIMAL_SECURITY_TEXT, encoding="utf-8")
    (repo / "SUPPORT.md").write_text("# Support\n", encoding="utf-8")
    (repo / "CONTRIBUTING.md").write_text("# Contributing\n", encoding="utf-8")
    (repo / "CODE_OF_CONDUCT.md").write_text("# Code of Conduct\n", encoding="utf-8")
    (repo / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True, exist_ok=True)
    (repo / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").write_text(
        "Please read `SUPPORT.md` first\n",
        encoding="utf-8",
    )
    (repo / ".github" / "ISSUE_TEMPLATE" / "documentation.yml").write_text(
        "Use this template for documentation drift\n",
        encoding="utf-8",
    )
    (repo / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text(
        "## Collaboration Surface\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "public_asset_provenance.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "assets:",
                "  - path: tests/fixtures/golden_input/doc.pdf",
                "    kind: public-test-fixture",
                "    status: repository-maintained-synthetic",
                "    license: MIT",
                "    sha256: 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                "    file_size_bytes: 5",
                "    notes: synthetic fixture",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "tests" / "fixtures" / "golden_input" / "doc.pdf").write_text("hello", encoding="utf-8")
    (repo / "docs" / "open_source_runbook.md").write_text(
        "bash tooling/gates/public_readiness_gate.sh repo\nbash tooling/gates/public_readiness_gate.sh release\n",
        encoding="utf-8",
    )
    (repo / "package.json").write_text(
        json.dumps({"scripts": {"public:readiness": "bash tooling/gates/public_readiness_gate.sh release"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    proc = subprocess.run(
        ["bash", str(REPO_ROOT / "tooling" / "gates" / "public_readiness_gate.sh"), "repo", "--root", str(repo)],
        cwd=str(tmp_path),
        text=True,
        capture_output=True,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "public-readiness-repo-surface: passed" in out


def test_public_asset_provenance_gate_fails_on_hash_drift(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "contracts" / "governance").mkdir(parents=True)
    (repo / "tests" / "fixtures" / "golden_input").mkdir(parents=True)
    (repo / "tests" / "fixtures" / "golden_input" / "doc.pdf").write_text("hello", encoding="utf-8")
    (repo / "contracts" / "governance" / "public_readiness_policy.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "required_asset_provenance_entries:",
                "  - tests/fixtures/golden_input/doc.pdf",
                "release_mode: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "governance" / "public_asset_provenance.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "assets:",
                "  - path: tests/fixtures/golden_input/doc.pdf",
                "    kind: public-test-fixture",
                "    status: repository-maintained-synthetic",
                "    license: MIT",
                "    sha256: deadbeef",
                "    file_size_bytes: 5",
                "    notes: synthetic fixture",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    proc = _run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "check_public_asset_provenance.py"),
            "--root",
            str(repo),
        ],
        repo,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "public-asset-provenance: failed" in out
    assert "sha256 drifted" in out
