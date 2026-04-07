from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_release_bundle_script_generates_expected_assets() -> None:
    script = (REPO_ROOT / "tooling" / "ci" / "build_release_bundle.sh").read_text(encoding="utf-8")
    assert 'validate_release_tag.sh" "$VERSION_TAG" bundle-only' in script
    assert "prepare_release_draft.py" in script
    assert "generate_release_evidence_report.py" in script
    assert "release-manifest.json" in script
    assert "pip_audit" in script
    assert "cyclonedx-json" in script
    assert 'npm --prefix "$REPO_ROOT/apps/webui" sbom' in script
    assert 'git -C "$REPO_ROOT" archive' in script
    assert "SHA256SUMS.txt" in script


def test_release_workflow_wires_release_assets_attestation_and_optional_release_publish() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "tag_name:" in workflow
    assert "publish_mode:" in workflow
    assert "bundle-only" in workflow
    assert "draft" in workflow
    assert "publish" in workflow
    assert "bash tooling/ci/validate_release_tag.sh" in workflow
    assert "bash tooling/gates/public_readiness_gate.sh release" in workflow
    assert "bash tooling/gates/platform_alignment_gate.sh" in workflow
    assert "bash tooling/gates/quality_gate.sh" in workflow
    assert "bash tooling/ci/build_release_bundle.sh" in workflow
    assert "bash tooling/ci/materialize_release_tag.sh" in workflow
    assert "--verify-tag" in workflow
    assert "--prerelease" in workflow
    assert "actions/attest-build-provenance@977bb373ede98d70efdf65b84cb5f73e068dcc2a" in workflow
    assert "subject-path: .runtime-cache/release-assets/*" in workflow
    assert "bash tooling/ci/verify_release_publish.sh" in workflow
    assert "release-verification-${{ inputs.tag_name }}" in workflow
    assert "gh release create" in workflow


def test_release_helpers_enforce_tag_policy_and_post_publish_verification() -> None:
    validate_script = (REPO_ROOT / "tooling" / "ci" / "validate_release_tag.sh").read_text(encoding="utf-8")
    verify_script = (REPO_ROOT / "tooling" / "ci" / "verify_release_publish.sh").read_text(encoding="utf-8")
    materialize_script = (REPO_ROOT / "tooling" / "ci" / "materialize_release_tag.sh").read_text(encoding="utf-8")

    assert "bundle-only|draft|publish" in validate_script
    assert "vMAJOR.MINOR.PATCH" in validate_script
    assert "alpha|beta|rc" in validate_script
    assert "RELEASE_REQUIRED_BRANCH" in validate_script
    assert "git check-ref-format" in validate_script
    assert "git push" in materialize_script
    assert "RELEASE_TAG_APPLY" in materialize_script
    assert "gh release view" in verify_script
    assert '"release", "download"' in verify_script
    assert "targetCommitish" in verify_script
    assert "movi-organizer-" in verify_script
    assert "release-manifest.json" in verify_script
    assert "python-runtime-sbom.cdx.json" in verify_script
    assert "webui-runtime-sbom.cdx.json" in verify_script
