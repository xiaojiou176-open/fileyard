from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_release_evidence_module():
    script = REPO_ROOT / "tooling" / "scripts" / "generate_release_evidence_report.py"
    spec = importlib.util.spec_from_file_location("generate_release_evidence_report", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_evidence_report_generator_writes_expected_sections(tmp_path: Path) -> None:
    output = tmp_path / "release-evidence.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tooling" / "scripts" / "generate_release_evidence_report.py"),
            "--root",
            str(REPO_ROOT),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ci_image_provenance"]["status"] == "wired"
    assert payload["release_asset_provenance"]["status"] == "workflow_wired"
    assert payload["sbom"]["status"] == "workflow_wired"
    assert payload["release_stage_policy"]["allowed_modes"] == ["bundle-only", "draft", "publish"]
    assert payload["post_publish_verification"]["status"] == "workflow_wired"
    assert payload["repo_side_release_reality"]["status"] == "verifiable_locally"
    assert payload["current_head_release_truth"]["operator_entrypoint"] == "npm run release:truth"
    assert payload["current_head_release_truth"]["summary_path"] == ".runtime-cache/logs/release-evidence/summary.json"
    assert payload["current_head_release_truth"]["status"] == payload["remote_release_boundary"]["status"]
    assert payload["current_head_release_truth"]["closure_rule"] == (
        "Only `published_release_verified` counts as verified published closure."
    )
    assert payload["current_head_release_truth"]["operator_read_order"][0] == "current_head_release_truth.status"
    assert "published_release_exists" in payload["current_head_release_truth"]["non_closure_statuses"]
    assert isinstance(payload["current_head_release_truth"]["safe_operator_statement"], str)
    assert isinstance(payload["current_head_release_truth"]["next_required_actions"], list)
    assert payload["current_head_release_truth"]["verified_published_closure"] == (
        payload["remote_release_boundary"]["status"] == "published_release_verified"
    )
    assert payload["target_release"]["tag_name"].startswith("v")
    assert payload["target_release"]["version_source"] == "pyproject.toml"
    assert payload["remote_release_boundary"]["status"] in {
        "pending_remote_workflow_run",
        "github_release_lookup_unavailable",
        "remote_release_not_current_head",
        "draft_exists_not_published",
        "published_release_exists",
        "draft_release_verified",
        "published_release_verified",
    }
    assert isinstance(payload["remote_release_boundary"]["required_actions"], list)
    assert payload["hardening_gap_vs_ci"]["status"] == "explicitly_accounted"
    assert payload["release_draft"] == ".runtime-cache/logs/release-draft.md"


def test_package_json_uses_public_release_evidence_entrypoint() -> None:
    package_json = (REPO_ROOT / "package.json").read_text(encoding="utf-8")
    assert '"release:evidence": "bash tooling/ci/run_release_evidence.sh"' in package_json
    assert '"release:truth": "bash tooling/ci/run_release_evidence.sh"' in package_json


def test_release_evidence_marks_remote_release_as_non_head_when_target_commit_differs(monkeypatch) -> None:
    module = _load_release_evidence_module()

    monkeypatch.setattr(
        module,
        "_gh_release_view",
        lambda _repo_root, _tag_name: (
            {
                "tagName": "v4.0.2-rc.0",
                "isDraft": False,
                "isPrerelease": True,
                "url": "https://example.invalid/releases/v4.0.2-rc.0",
                "targetCommitish": "a0038482efe7a700e59bffb07eedb00423e24aa0",
                "publishedAt": "2026-03-25T12:50:38Z",
            },
            None,
        ),
    )
    monkeypatch.setattr(module, "_load_release_verify_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "_git_rev_parse",
        lambda _repo_root, ref: "c5ae29584fb8915fbe63072c963c76203322e38a" if ref == "HEAD" else None,
    )

    boundary = module._build_remote_release_boundary(REPO_ROOT, "v4.0.2-rc.0")

    assert boundary["status"] == "remote_release_not_current_head"
    assert boundary["remote_release"]["target_commitish"] == "a0038482efe7a700e59bffb07eedb00423e24aa0"
    assert boundary["current_head_commit"] == "c5ae29584fb8915fbe63072c963c76203322e38a"
