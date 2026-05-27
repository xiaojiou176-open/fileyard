# Open Source Runbook

This runbook is canonical for public, release, and platform-boundary semantics.
Repository docs are not a live platform dashboard.
Product-positioning shorthand in public surfaces should stay: `Fileman` as the brand, `fileman` as the repo/CLI, a local-first review-first workbench rather than a hosted SaaS or autonomous organizer, and `Fileman MCP v1` as a repo-local stdio extension surface rather than a hosted agent platform.

The target public shape is:

- public source repository
- GitHub Releases as the canonical release surface
- limited-maintenance collaboration
- no promise of PyPI or public container distribution

In short: limited-maintenance open source + a GitHub source repo + GitHub Releases.

## Platform Truth Surfaces (Dynamic Projection)

Do not freeze platform state inside a long-lived document. Platform state is like an airport departure board: check the **live screen**, not a copied note in a travel guide.

<!-- BEGIN GENERATED: open-source-platform-truth -->
> Auto-generated: public-surface and platform-state policy facts live in [generated governance reference](reference/governance_truth.generated.md), and [required checks matrix](required_checks_matrix.md).

- **Repo public readiness gate**: `bash tooling/gates/public_readiness_gate.sh repo`
- **Release public readiness gate**: `bash tooling/gates/public_readiness_gate.sh release`
- **Platform alignment gate**: `bash tooling/gates/platform_alignment_gate.sh`
- **Release-mode policy**: tracked public files=`yes` / public repo=`yes` / PVR=`yes` / branch protection=`yes`
<!-- END GENERATED: open-source-platform-truth -->

To inspect the live GitHub platform state directly, run:

```bash
gh repo view --json nameWithOwner,url,isPrivate,defaultBranchRef
gh api repos/<owner>/<repo>/private-vulnerability-reporting
gh api repos/<owner>/<repo>/branches/main/protection
gh release list --limit 5
```

What you actually need to verify:

- Whether the repo-side public surface is complete.
- Whether release-mode constraints are satisfied.
- Whether GitHub is actually exposing the required checks, PVR, release trail, and zero-open-alert security posture.

> Do not mistake a repo-mode pass for full platform closure. `repo-side` only proves that the repository-facing public surface is ready; it does not prove that GitHub has aligned required checks, PVR, or default-branch reality.
> If branch protection or required checks return 404/permission-limited responses in the current `gh` session, treat that as `platform-side-query-blocked`, not as a silent pass.
> Snapshot scope labels used here: `repo-side-only` and `platform-side-not-fresh`.

## Minimum Pre-Release Checks

```bash
bash tooling/runtime/bootstrap_env.sh
bash tooling/gates/public_readiness_gate.sh repo
bash tooling/gates/public_readiness_gate.sh release
bash tooling/gates/platform_alignment_gate.sh
bash tooling/gates/sensitive_surface_gate.sh --mode all
bash tooling/gates/public_artifact_audit.sh
bash tooling/docs/check_docs_scope.sh
bash tooling/docs/docs_smoke.sh --install-smoke
bash tooling/gates/quality_gate.sh
bash tooling/gates/history_secret_scan.sh
```

- `bash tooling/gates/quality_gate.sh`: the only delivery-complete signal. Only a fresh pass lets this snapshot be described as complete.
- `bash tooling/docs/docs_smoke.sh --install-smoke`: only smoke-checks command examples and packaging/installability docs. It is not the full docs governance verdict by itself, and this search-before-write note is part of keeping docs navigation and gate boundaries honest.
- `bash tooling/gates/public_readiness_gate.sh repo`: checks whether the repo-side public surface is complete.
- `bash tooling/gates/public_readiness_gate.sh release`: performs the strict pre-release comparison between tracked files and GitHub platform truth.
- `bash tooling/gates/platform_alignment_gate.sh`: closes the loop between release-mode checks and required checks / branch protection as the dedicated platform gate.
- `bash tooling/gates/sensitive_surface_gate.sh --mode all`: blocks tracked absolute user-home paths, personal contact data, unsafe header/token dumps, and tracked log/db/key-style artifacts before they leak into the repo surface.
- `bash tooling/gates/public_artifact_audit.sh`: verifies that declared public assets and synthetic public fixtures stay inside governed roots, keep allowed classifications, and do not carry obvious dump/secret-style content in text-readable artifact surfaces.
- GitHub-hosted workflow security lanes should stay green for current closeout truth: `codeql`, `dependency-review`, `zizmor`, `trivy-fs`, and `trufflehog`.
- Release/platform verification now also requires **zero open GitHub code-scanning alerts** and **zero open GitHub secret-scanning alerts**; if the current `gh` context cannot query them, treat that as `platform-side-query-blocked`, not as a silent pass.
- If those gates report `query-blocked-permission-context`, rerun them with an admin-capable GitHub context before describing platform closure as verified.

## Release Truth

Use these entrypoints for release-facing facts:

```bash
npm run release:draft
npm run release:evidence
npm run release:truth
```

Treat `npm run release:truth` as the operator-facing entrypoint for current-head release truth.

Only `published_release_verified` counts as a verified published closure.

## Manual Platform Checklist

1. Confirm the repository is public and the default branch is `main`
2. Verify branch protection and required checks on GitHub
3. Verify Private Vulnerability Reporting when the platform supports it
4. Confirm `CODEOWNERS`, issue templates, `SECURITY.md`, and `SUPPORT.md` are live on the default branch
5. Verify the release draft or published release against the current tag and assets

Public / release / platform readiness is not the same thing as product-value maturity.
