# Third-Party Notices

This file records the most important third-party dependencies and public asset provenance notes for the current public surface of this repository.
It is not a full SBOM; the complete dependency surface still comes from lockfiles, `contracts/upstreams/*`, and package-manager metadata.

## Runtime / Tooling Dependencies

- Python dependencies: managed by the repository root `pyproject.toml`, `tooling/requirements.lock.txt`, and `tooling/requirements-dev.lock.txt`.
- Frontend dependencies: managed by `apps/webui/package.json` and `apps/webui/package-lock.json`.
- Upstream governance policy: see `contracts/upstreams/upstream_inventory.yaml` and `contracts/upstreams/license_policy.yaml`.

## Assets And Notices

Canonical provenance ledger for repository-authored public assets and synthetic public test fixtures:
`contracts/governance/public_asset_provenance.yaml`

Repo-side trust posture for those public assets and synthetic fixtures is enforced by:
`bash tooling/gates/public_artifact_audit.sh`

- `apps/webui/public/fileman-mark.svg`
  - Status: repository-authored asset
  - License: MIT (same as repository)
  - Notes: replaces the default Vite favicon for clearer provenance.

- IBM Plex Sans webfont via `@fontsource/ibm-plex-sans`
  - Surface: `apps/webui/package.json`
  - License family: SIL Open Font License 1.1
  - Notes: consumed through the npm package, not vendored as raw font files in the repository.

- Test fixtures under `tests/fixtures/golden_input/`
  - Status: repository-maintained synthetic fixtures for deterministic tests
  - Notes: these fixtures are used for offline/golden regression coverage and are not product assets.

## Not Included

- This file does not claim that every transitive dependency has a human-written notice line here.
- If a future asset or fixture provenance cannot be explained conservatively, replace or remove it before relying on public redistribution.
