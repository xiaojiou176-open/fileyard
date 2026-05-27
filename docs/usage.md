# Movi Detailed Operator Guide

This file is the detailed operator guide.
Detailed operator guide for runtime commands, API usage, and operator-facing execution notes.
This guide is for people who want the full operator route, not just the
fast first-look flow from [README.md](../README.md).

If you only need the public overview, go back to [README.md](../README.md).
If you need release or platform-boundary rules, continue with
[docs/open_source_runbook.md](./open_source_runbook.md).

This repository is a limited-maintenance open-source project.
The product promise stays intentionally small: **review-first, AI-assisted, dry-run before execute, rollback-ready, local-first**.

## What This Guide Is For

Use this document when you need one of these:

- A copyable operator route with explicit paths
- The full CLI boundary for `analyze`, `apply`, and `rollback`
- A clearer answer to "which command should I run next?"

## Copyable Config Example

If you want an explicit config file path in your command, use:

```bash
--config ./contracts/runtime/config.example.toml
```

That flag is useful when you want a command that can be copied into an
issue, a docs example, or a repeatable local script without depending on
hidden shell state.

## Core Flow

Think of the workflow as three separate steps:

- `analyze`: inspect files and write a manifest
- `apply`: execute filesystem changes from the manifest
- `rollback`: deterministically undo by manifest

`analyze` may call Gemini.
`apply` and `rollback` do not call Gemini.

When you use the browser surface, the practical route is a little more guided:

- `Movi Inbox` discovers or registers intake sources, then hands a chosen batch into Analyze
- `Analyze` drafts the manifest with optional Strategy Pack defaults
- `Movi Review` is still the human decision gate, with collection slices, learned suggestions, and overlay-only actions
- `Report` acts like an after-action board and can send you back into a focused Review pass

## Naming Baseline

- **Movi** is the product brand.
- **`fileyard`** is the repository and CLI/runtime identity.
- **Movi Review**, **Movi Rules**, and **Movi Inbox** are the current stable product-surface names.
- **Movi Copilot** is the current review-only guidance layer.
- **Movi MCP v1** is the current local-first stdio surface for agent/developer integrations.

## Fast Operator Route

This route is longer than the README quickstart because it is meant for
people who want explicit paths and repeatable local outputs.

```bash
bash tooling/runtime/bootstrap_env.sh
mkdir -p .runtime-cache/operator-demo
MOVI_ALLOW_HOST_EXECUTION=1 bash tooling/runtime/run_analyze.sh \
  --offline \
  --config ./contracts/runtime/config.example.toml \
  --input ./tests/fixtures/golden_input \
  --manifest ./.runtime-cache/operator-demo/manifest.jsonl \
  --report ./.runtime-cache/operator-demo/analyze-report.json
cp ./.runtime-cache/operator-demo/manifest.jsonl ./.runtime-cache/operator-demo/manifest.apply.jsonl
MOVI_ALLOW_HOST_EXECUTION=1 bash tooling/runtime/run_apply.sh \
  --config ./contracts/runtime/config.example.toml \
  --manifest ./.runtime-cache/operator-demo/manifest.apply.jsonl \
  --input-root ./tests/fixtures/golden_input \
  --output ./.runtime-cache/operator-demo/output \
  --dry-run \
  --verify-sha1 \
  --report ./.runtime-cache/operator-demo/apply-report.json
```

Start real execution only after a dry run and review-queue pass.

## Browser Surface Route

If you want the app shell instead of the CLI:

```bash
npm run dev:stack
```

This starts the Web API and WebUI so you can walk through setup, analyze,
Movi Review, Movi Rules, apply, report, rollback, and Movi Inbox from the browser. Inside the review workbench, saved rules can be reloaded into Rule Studio and learned suggestions can be promoted into an editable draft before you apply them to the overlay.
The current Wave 2 surface also adds a visible `Movi Copilot v1` panel for review-only guidance, batch triage that writes to the overlay rather than disk, explainable learned suggestions that can be accepted or dismissed, and a `rule from examples` helper that seeds Rule Studio with transparent heuristics instead of auto-executing changes.
The current Wave 3 surface makes the front door more continuous: Inbox can explicitly launch Analyze with batch context, Strategy Packs are explained as analyze templates instead of hidden settings, Collection Intelligence v2 explains why a slice belongs together, and Report can loop you back into Review with clear focus filters such as conflicts or learning suggestions.
Wave 4 adds `Movi MCP v1` as the agent/developer-facing extension surface. It stays stdio-first and local-first, and it only exposes review-safe tools plus read-only resources rather than a hidden execute shortcut.

Important promise boundary:

- the current browser surface is a review-first workbench, not a hosted SaaS
- AI assists planning and review, but real execution still goes through deterministic `apply`
- Strategy Packs, learned suggestions, and report-to-review links all stay advisory or routing-only; they do not auto-execute changes
- `Movi MCP v1` is live as a thin agent/developer surface, but it still inherits the same review-first and dry-run-first boundaries
- future surfaces such as deeper `Movi Copilot` automation should still be read as roadmap language, not live product claims

## Movi MCP v1

`Movi MCP v1` is the agent-safe extension surface for this repository.

In plain language: it gives an LLM or automation client a supervised service window into the same workflow you already use in the app. It can inspect queues, read reports, patch overlays, preview rules, and queue dry-run apply jobs, but it does not get a secret door that bypasses review.

Use it when you want:

- stdio/local-first integration for Claude, Codex, Cursor, or another MCP-capable client
- the same review-safe semantics without hand-rolling Web API calls
- a machine-readable tool and resource surface that still obeys `overlay-only` and `dry-run before execute`

Do not use it as if it were:

- a hosted API platform
- a direct filesystem mutation tool
- a shortcut around `overlay -> resolved snapshot -> dry-run -> execute`

Start with [docs/mcp.md](./mcp.md) for the capability map and [docs/developer_guide.md](./developer_guide.md) for the surface-selection guide.

## Operator Notes

- Use `bash tooling/runtime/run_analyze.sh --offline` when you need a no-network manifest path
- Keep `rollback` bounded by `--allowed-root`
- Pair `--trust-manifest-input-root` with an explicit allowlist
- For release, platform, and public-boundary questions, route to [docs/open_source_runbook.md](./open_source_runbook.md)

## Space Governance

Think of Movi's runtime footprint as four primary rails, plus one infrastructure-only surface:

- `repo-local residue`: checkout-local runtime noise such as `.runtime-cache`
- `machine cache`: governed host-side caches under `~/.cache/fileyard`; in the container-first model this is the fallback lane, not the canonical runtime lane
- `docker runtime`: the canonical container-first runtime surface, including `movi-ci:local`, named volumes, and repo-related build cache
- `workspace evidence`: run bundles and durable artifacts under `<workspace-root>/.movi`
- `shared runner workdir`: shared CI infrastructure workdirs outside single-repo ownership; this is infrastructure maintenance, not normal single-repo cleanup

Use the cleanup entrypoint that matches the bucket you actually want to trim:

```bash
# repo-local residue only
bash tooling/cleanup/prune_repo_runtime.sh

# safest machine-cache cleanup: Python bytecode only
bash tooling/cleanup/prune_machine_cache.sh --safe

# broader rebuildable machine caches: pycache + pip + npm + playwright + pytest-runtime
bash tooling/cleanup/prune_machine_cache.sh --rebuildable

# aggressive host fallback reclaim: rebuildable caches + governed host venv
bash tooling/cleanup/prune_machine_cache.sh --aggressive-host

# container-first docker runtime audit
bash tooling/cleanup/prune_docker_runtime.sh --dry-run

# repo-related docker build cache only
bash tooling/cleanup/prune_docker_runtime.sh --rebuildable

# explicit high-risk docker reclaim path (still opt-in for image/volumes)
bash tooling/cleanup/prune_docker_runtime.sh --aggressive

# workspace retention cleanup (runs/artifacts only; manifests stay intact)
bash tooling/cleanup/prune_workspace_runtime.sh --dry-run
```

Important boundary:

- `bash tooling/runtime/runtime_reset.sh --confirm-workspace-reset` is **not** a routine cache cleanup. It prunes repo-local residue and then clears workspace `.movi` state.
- `bash tooling/cleanup/prune_docker_runtime.sh --aggressive --include-image --include-volumes` is intentionally separate from routine cleanup because it can reclaim the current canonical Docker runtime surface.
- `bash tooling/ci/prune_shared_runner_workdirs.sh --dry-run` is historical-only and no longer part of the active hosted-first operating model.

## Where To Read What

- Public overview and minimal truth routes: [README.md](../README.md)
- Release and platform boundary: [docs/open_source_runbook.md](./open_source_runbook.md)
- Architecture and execution boundaries: [docs/architecture.md](./architecture.md)
- MCP and agent surface: [docs/mcp.md](./mcp.md)
- Developer entry guide: [docs/developer_guide.md](./developer_guide.md)
- Brand baseline: [docs/brand_positioning.md](./brand_positioning.md)
- Search-intent map: [docs/seo_landing_map.md](./seo_landing_map.md)

<!-- BEGIN GENERATED: script-readme-release-identity -->
> Auto-generated: the current source package version comes from `pyproject.toml`. `current-head release` boundaries depend on local/CI runtime evidence, and a clean checkout does not carry a repo-local release evidence summary by default.

- **Current source package version**: `4.0.5`
- **Current current-head release tag**: `v4.0.5`
- **Current current-head release boundary**: `requires_local_release_evidence`
- **Current release publish status**: `unknown in clean checkout`
- **How to read this**: run `npm run release:truth`, then read `current_head_release_truth.status` before making current-head release claims.
- **Verified published closure**: only `published_release_verified` can be described as a verified published closure.
<!-- END GENERATED: script-readme-release-identity -->

## Runtime Topology

<!-- BEGIN GENERATED: script-readme-runtime-topology -->
> Auto-generated: runtime services, default ports, runtime paths, and entrypoint facts live in [generated runtime topology](docs/reference/runtime_topology.generated.md).

- **Compose services**: `movi-ci`, `movi-web-api`, `movi-webui`
- **Web API bind**: `loopback:18080`
- **WebUI bind**: `loopback:5173`
- **Persistent workspace docs alias**: `<workspace-root>`
- **Repo-local cache docs alias**: `<repo-runtime-cache>`
<!-- END GENERATED: script-readme-runtime-topology -->

## Web API Summary

<!-- BEGIN GENERATED: script-readme-web-api-routes -->
> Auto-generated: current Web API facts come from `contracts/api/web_api.openapi.yaml`; the full method/path list lives in [generated reference](docs/reference/web_api_routes.generated.md).

- **Jobs / history**: `/api/jobs`, `/api/jobs/history`, `/api/jobs/stream`, `/api/jobs/{job_id}`, `/api/jobs/{job_id}/review-queue`, `/api/jobs/{job_id}/review-queue/batch-triage`, `/api/jobs/{job_id}/review-rules/apply`, `/api/jobs/{job_id}/review-rules/from-examples`, `/api/jobs/{job_id}/review-rules/preview`
- **Job events**: `/api/jobs/{job_id}/events`, `/api/jobs/{job_id}/events/stream`, `/api/jobs/{job_id}/stream`
- **Manifest operations**: `/api/jobs/{job_id}/manifest`, `/api/jobs/{job_id}/manifest/batch`, `/api/jobs/{job_id}/manifest/conflicts`, `/api/jobs/{job_id}/manifest/conflicts/resolve`, `/api/jobs/{job_id}/manifest/rows/{row_id}`, `/api/jobs/{job_id}/manifest/view`, `/api/jobs/{job_id}/manifest/{row_id}/preview`
- **Job actions**: `/api/jobs/analyze`, `/api/jobs/apply`, `/api/jobs/rollback`, `/api/jobs/{job_id}/cancel`, `/api/jobs/{job_id}/retry`
- **Report / audit**: `/api/jobs/{job_id}/audit`, `/api/jobs/{job_id}/report`
- **Preferences**: `/api/preferences/learned-rules`, `/api/preferences/naming-templates`, `/api/preferences/review-rules`, `/api/preferences/runtime`, `/api/preferences/runtime/validate`, `/api/preferences/strategy-packs`, `/api/preferences/views`, `/api/preferences/watch-sources`
- `overlay` / `resolved snapshot` are internal model and file-output concepts, not stable public HTTP routes.
<!-- END GENERATED: script-readme-web-api-routes -->

## Governance And Completion

<!-- BEGIN GENERATED: script-readme-governance-truth -->
> Auto-generated: delivery-complete truth, governance scorecard truth, hosted CI facts, and platform-alignment facts live in [generated governance reference](docs/reference/governance_truth.generated.md), [required checks matrix](docs/required_checks_matrix.md), and [runner contract](docs/runner_contract.md).

- **Delivery-complete gate**: `bash tooling/gates/quality_gate.sh`
- **Repo governance scorecard**: `bash tooling/gates/verify_repo_final.sh`
- **Platform alignment gate**: `bash tooling/gates/platform_alignment_gate.sh`
- **Hosted CI model**: `github-hosted-only`
- **Protected sensitive environments**: `owner-approved-sensitive`
<!-- END GENERATED: script-readme-governance-truth -->

Delivery-complete truth for the current snapshot still comes only from a
fresh pass of `bash tooling/gates/quality_gate.sh`.
Repo-side governance scorecard, not delivery completion:
`bash tooling/gates/verify_repo_final.sh`.

## CI Summary

<!-- BEGIN GENERATED: script-readme-ci-governance-summary -->
> Auto-generated: CI truth-chain, failure-domain policy, navigation entrypoints, and executable gate facts come from [required checks matrix](docs/required_checks_matrix.md), [runner contract](docs/runner_contract.md), and [ci.yml](../.github/workflows/ci.yml).

- **Canonical truth path**: `build-ci-image -> change-detection -> {webui-build-test, quality-gate-full} -> functional-gate -> test`
- **Canonical gate**: `quality-gate-full`
- **Supplemental gates**: `webui-build-test` (frontend correctness), `functional-gate` (critical smoke), `test` (Python version parity)
- **Dual failure-domain required jobs**: None
- **Shared-pool-only required jobs**: None
- **Side workflows**: `pre-commit` bootstraps directly on hosted runners, while `live-integration` and `mutation-manual` reuse `reusable-build-runtime-image.yml`; runtime image build keeps provenance artifact wiring when the platform supports attestations.
- **Drift / evidence surfaces**: `nightly-drift-audit.yml`, `collect_ci_run_metrics.py`, `generate_ci_evidence_bundle.py`.
- **Local auxiliary evidence**: `npm run ci:local` writes repo-local CI metrics, a repo-local evidence bundle, and governed upstream receipts under the repo-local runtime cache directory; these are local derived reports, not Branch Protection truth. Read `truth.truth_class`, `truth.remote_traceability`, and `truth.authoritative_terminal_receipt` before treating the bundle as anything stronger. Older pass receipts remain historical audit evidence only; current closeout wording must follow the latest canonical terminal receipt.
- **Developer fallback**: use `bash tooling/gates/pre_push_gate.sh` (`standard/strict/full`) for fast local feedback before remote CI.
<!-- END GENERATED: script-readme-ci-governance-summary -->
