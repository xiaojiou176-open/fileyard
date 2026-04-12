# Movi

Movi is a review-first local file organizer and workbench for messy photos, screenshots, documents, and audio. It lets AI assist with the manifest first, then lets you inspect, label, and approve the plan before deterministic `apply` or `rollback` touches your files.

[Safe First Look](#safe-first-look) · [10-Second Tour](#10-second-tour) · [Good Fit / Not A Fit](#good-fit--not-a-fit) · [Public Proof](docs/public_proof.md) · [Docs](docs/index.md) · [Distribution](DISTRIBUTION.md) · [Integrations](INTEGRATIONS.md) · [Submission Manifest](manifest.yaml) · [MCP Descriptor](server.json) · [Review-First Skill Packet](examples/skills/README.md) · [OpenClaw Bundle](examples/openclaw/README.md) · [Browser Surface](#browser-surface) · [Releases](https://github.com/xiaojiou176-open/movi-organizer/releases) · [Discussions](https://github.com/xiaojiou176-open/movi-organizer/discussions) · [Security](SECURITY.md) · [Movi MCP v1](docs/mcp.md) · [Codex Integration](docs/codex_mcp.md) · [Claude Code Integration](docs/claude_code_mcp.md) · [Developer Guide](docs/developer_guide.md)

![Movi overview showing mixed files flowing into manifest review and organized output](docs/assets/storefront/hero-movi-overview.svg)

Movi is a **review-first local AI file organizer**. It turns a chaotic intake folder into a review queue, then into a reviewed manifest, and only then into safer file moves you can dry-run, audit, and roll back. The current shipped surface stays intentionally narrow: `Movi Review`, `Movi Rules`, `Movi Inbox`, `Movi Copilot v1`, and `Movi MCP v1` all describe real current surfaces, but they still stay inside one safety story instead of pretending Movi is an autonomous organizer.

Public maintenance posture: limited-maintenance open source.

Current proof posture: reproducible smoke-tier evidence with a live release trail, Pages front door, and repo-side safety gates. It is not broad benchmark-grade proof yet, but the current front door already clears a truthful public-entry bar, and the proof routes stay explicit in [Public Proof](docs/public_proof.md) instead of being buried in operator-only docs.

## Canonical Public Roots

Read Movi like a workshop with one front desk and several labeled shelves:

- **Canonical public root:** this root [`README.md`](./README.md) plus the root [`manifest.yaml`](./manifest.yaml)
- **Canonical pure-MCP registry descriptor:** [`server.json`](./server.json)
- **Current pure-skills packet:** [`examples/skills/`](./examples/skills/)
- **Host-specific supporting bundle:** [`examples/openclaw/`](./examples/openclaw/)
- **Pure-MCP support surface:** [`docs/mcp.md`](./docs/mcp.md)
- **Pure-MCP runtime implementation guide:** [`apps/mcp/README.md`](./apps/mcp/README.md)

## Why Movi Exists

Cleaning up a mixed folder usually fails for one of two reasons: either the tool is too manual, or the AI is allowed to move files before you can inspect the plan.

Movi splits those jobs on purpose:

- `analyze` is where AI helps understand the files
- `apply` is where deterministic rules execute the approved manifest
- `rollback` is where you can undo with the same paper trail

Think of it like moving house: AI makes the packing list, but the moving crew still follows an approved checklist instead of guessing in the hallway.

## What You Get

- **Review-first workflow**: AI drafts the manifest, but file changes only happen after you inspect the plan.
- **AI-assisted, not AI-autonomous**: Movi helps draft and suggest, but deterministic execution still waits for your approval.
- **Dry-run by default**: you can see what Movi wants to do before a real rename or move happens.
- **Rollback-ready workflow**: the same manifest chain supports recovery when a batch needs to be undone.
- **Local-first runtime**: your folders, manifests, and reports stay under your chosen workspace root.
- **Operator-grade guardrails**: quality gates, structured logs, and release runbooks exist for people who need deeper operational truth.

## Public Proof At A Glance

If you are asking, "is this a real product surface or just a careful README," the shortest honest answer is:

- **Public source repo + GitHub Releases**: the release trail is public on [GitHub Releases](https://github.com/xiaojiou176-open/movi-organizer/releases).
- **Live Pages front door**: the current public landing route is [xiaojiou176-open.github.io/movi-organizer](https://xiaojiou176-open.github.io/movi-organizer/).
- **Review-first proof, not autonomy theater**: the repo ships a fixture-backed safe first look, dry-run apply, rollback boundaries, and a real MCP surface that still stays behind review-safe semantics.
- **Honest boundary language**: Movi does not claim hosted SaaS, zero-review file mutation, or public benchmark-grade proof that the repo has not actually earned yet.

If you want the full outsider-facing proof map, open [Public Proof](docs/public_proof.md). If you want the shortest hands-on route, stay on this page and run [Safe First Look](#safe-first-look).

## Public Language Contract

For external readers, Movi keeps one simple language rule:

- **English-first public truth surfaces**: this root `README.md`, [`DISTRIBUTION.md`](./DISTRIBUTION.md), [`INTEGRATIONS.md`](./INTEGRATIONS.md), [`manifest.yaml`](./manifest.yaml), and any later root truth surface only after it is explicitly synced to the same wording standard.
- **Bilingual or locale-switchable product surfaces**: the WebUI keeps English as the default locale and can switch to `zh-CN` for operator comfort, walkthroughs, and day-to-day use.
- **Why this split exists**: public listings, review threads, and release receipts need one stable English contract so outside readers do not have to compare two drifting versions of the same claim, while the product itself can still meet operators where they are.
- **Honesty rule**: translations may improve usability, but they must not silently outrun or override the English canonical public truth.

## Product Surface Baseline

- **Movi**: the main product brand.
- **`movi-organizer`**: the repository name and CLI/runtime identity.
- **Movi Review**: the review queue and manifest-approval layer you use before execution.
- **Movi Rules**: the rule authoring surface for reusable review logic and rule drafts.
- **Movi Inbox**: the intake and scan surface for watch sources and incoming batches. It can hand a batch into Analyze, but it is not an autonomous organizer.
- **Movi Copilot**: the current review-only guidance layer. It summarizes queue risk, highlights rule opportunities, and helps draft edits without touching `apply`.
- **Movi MCP v1**: a local-first stdio MCP surface for agents and developers. It exposes review-safe tools and resources for analyze, review, manifest editing, and dry-run preview, but it does not bypass `overlay -> resolved snapshot -> dry-run -> execute`.
- **Strategy Packs**: reusable analyze templates that prefill model, category hints, and worker defaults for recurring batch types. They stay template-only rather than becoming a second platform.

## AI And Agent Fit

Movi belongs to a very specific lane:

- **Category**: review-first local AI file organizer and workbench
- **Hotness hook**: stdio-first MCP for Codex, Claude Code, and other local MCP-capable clients
- **Outcome**: safer file organization with manifest review, dry-run preview, and rollback-ready recovery

Current honest ecosystem fit:

- **Primary fit**: Codex and Claude Code, because `Movi MCP v1` already ships as a local-first stdio surface with review-safe tools
- **Secondary ecosystem fit**: Cursor and other local MCP-capable clients, because the transport and tool surface already match their integration model
- **Comparison-only fit**: OpenHands and OpenCode, because the repo has a real MCP and API substrate they can consume, but no dedicated first-party setup surface or branded workflow yet

## Public Distribution Snapshot

- **ClawHub**: listed live, but the current page still shows `Moderation verdict: suspicious` and `Detected: suspicious.vt_suspicious`.
- **OpenHands**: submitted through `OpenHands/extensions#161`; current GitHub state is `OPEN / REVIEW_REQUIRED / BLOCKED`.
- **Goose Skills Marketplace**: submitted through `block/Agent-Skills#25`; validation passed, and the current visible blocker is upstream security review / CODEOWNERS handling.
- **agent-skill.co source repo**: submitted through `heilcheng/awesome-agent-skills#181`; the current visible blocker is upstream preview authorization rather than a missing Movi packet.
- **Official MCP Registry**: `not_submitted`.
- **awesome-opencode**: `not_submitted`, because Movi is still a review-first local MCP workflow rather than an Opencode-centered project/resource fit.
- **GHCR**: `not_published`.
- **Package and Docker later lanes**: no verified public receipt today.

## 10-Second Tour

![Movi 10-second tour showing intake, manifest review, and dry-run apply](docs/assets/storefront/ten-second-tour-movi.svg)

1. Drop a messy intake batch into one folder.
2. Let `analyze` draft a manifest and a review queue you can triage before touching the file system.
3. Keep `apply` in dry-run mode until the plan looks right, then rely on rollback-ready receipts if a batch needs to be undone.

## Before / After

![Before and after comparison showing a mixed intake folder and reviewed organized output](docs/assets/storefront/before-after-movi.svg)

Movi is built for the frustrating middle ground between "do everything by hand" and "let AI rename files without supervision." The before/after difference comes from review-first planning, not hidden mutation.

## Good Fit / Not A Fit

| Good fit | Not a fit |
| :-- | :-- |
| You want AI help classifying messy folders without giving AI direct file-move authority | You want a zero-review magic organizer that mutates files immediately |
| You need a repeatable audit trail for screenshots, PDFs, photos, and recordings | You want a hosted SaaS with team dashboards and always-on support |
| You care about dry-run, manifest review, and rollback | You need enterprise SLAs or guaranteed support windows |

## Safe First Look

This safe first look uses the built-in sample fixture set and keeps `apply` in `--dry-run` mode. It demonstrates the review-first loop on governed fixture data, not a public-tier benchmark or a recorded human baseline.

### 1. Bootstrap the governed runtime

```bash
bash tooling/runtime/bootstrap_env.sh
```

### 2. Generate a sample manifest without Gemini calls

```bash
mkdir -p .runtime-cache/storefront-demo
MOVI_ALLOW_HOST_EXECUTION=1 bash tooling/runtime/run_analyze.sh \
  --offline \
  --config ./contracts/runtime/config.example.toml \
  --input ./tests/fixtures/golden_input \
  --manifest ./.runtime-cache/storefront-demo/manifest.jsonl \
  --report ./.runtime-cache/storefront-demo/report.json
```

### 3. Preview the file moves without changing anything

```bash
cp ./.runtime-cache/storefront-demo/manifest.jsonl ./.runtime-cache/storefront-demo/manifest.apply.jsonl
MOVI_ALLOW_HOST_EXECUTION=1 bash tooling/runtime/run_apply.sh \
  --config ./contracts/runtime/config.example.toml \
  --manifest ./.runtime-cache/storefront-demo/manifest.apply.jsonl \
  --input-root ./tests/fixtures/golden_input \
  --output ./.runtime-cache/storefront-demo/output \
  --dry-run \
  --verify-sha1 \
  --report ./.runtime-cache/storefront-demo/apply-report.json
```

After step 3, inspect:

- `./.runtime-cache/storefront-demo/manifest.jsonl`
- `./.runtime-cache/storefront-demo/manifest.apply.jsonl`
- `./.runtime-cache/storefront-demo/report.json`
- `./.runtime-cache/storefront-demo/apply-report.json`

What this route proves:

- the review-first `analyze -> manifest -> dry-run apply` loop works on the canonical fixture pack
- receipts and reports are generated in governed local paths

What this route does not prove yet:

- a recorded human baseline for the same batch
- public-tier sample scale or long-run user outcomes

If this quickstart fails, the next stop is [docs/usage.md](docs/usage.md), which explains the full operator route and runtime expectations.

## Browser Surface

If you want to explore the workflow as an app instead of a shell session:

```bash
npm run dev:stack
```

That route starts the Web API and WebUI so you can walk through setup, analyze, `Movi Review`, `Movi Rules`, apply, report, rollback, and `Movi Inbox` from the browser.
Inside the current browser flow, Inbox can hand a batch into Analyze, Analyze can hand the drafted manifest into Review, Collection Intelligence v2 helps you judge one batch slice at a time, and Report can send you back into a focused Review pass for conflicts, human-check rows, or learning suggestions.

## Release Trail

If you want the public release storyline instead of the repo history, start with the latest [GitHub Releases](https://github.com/xiaojiou176-open/movi-organizer/releases) and use [CHANGELOG.md](CHANGELOG.md) for the unreleased lane.

## Why You Can Trust The Workflow

- **The manifest is the source of truth**: review happens before file mutation.
- **`apply` and `rollback` stay deterministic**: AI helps plan, not execute arbitrary moves.
- **Safety language is explicit**: `dry-run`, `allowed-root`, and manifest validation are first-class, not buried extras.
- **Proof routes are explicit**: live release, Pages, and deeper operator truth routes are linked directly instead of being hidden in internal-only notes.

## Brand And Landing Notes

- Brand positioning and naming baseline: [docs/brand_positioning.md](docs/brand_positioning.md)
- SEO intent map and future landing plan: [docs/seo_landing_map.md](docs/seo_landing_map.md)
- Movi MCP v1 surface and safety boundary: [docs/mcp.md](docs/mcp.md)
- Developer and agent entry guide: [docs/developer_guide.md](docs/developer_guide.md)
- High-intent landing page for review-first search traffic: [docs/review_first_ai_file_organizer.md](docs/review_first_ai_file_organizer.md)
- Agent integration pages: [Codex Integration](docs/codex_mcp.md), [Claude Code Integration](docs/claude_code_mcp.md)
- Use-case pages: [Photo Organizer](docs/photo_organizer.md), [Screenshot Organizer](docs/screenshot_organizer.md), [Receipt Organizer](docs/receipt_organizer.md)

## Agent And Developer Surface

If you are wiring Movi into another tool or an agent workflow, use the surface that matches the job:

- **CLI** for full operator runs and reproducible shell workflows.
- **Web API** for local app integration and debugging.
- **Movi MCP v1** for agent-facing, stdio-first access to the same review-safe workflow.

If you want the shortest client-specific route instead of the generic MCP page:

- **Codex**: start with [docs/codex_mcp.md](docs/codex_mcp.md)
- **Claude Code**: start with [docs/claude_code_mcp.md](docs/claude_code_mcp.md)
- **Builder / substrate view**: start with [docs/developer_guide.md](docs/developer_guide.md)

Think of it like a workshop with three doors: the CLI is the loading dock, the Web API is the control room, and Movi MCP is the supervised service window for agents. None of those doors secretly lead around review.

## FAQ

### Does Movi call Gemini every time

No. `analyze` may call Gemini when you are not in offline mode. `apply` and `rollback` do not call Gemini.

### Can I try it without risking my real folders

Yes. The quickstart above uses fixture files and keeps `apply` in `--dry-run` mode.

### Is this a hosted product

No. Movi is a limited-maintenance open-source repository with a local-first workflow. Bring your own environment and review the manifest before real changes.

## Runtime Cleanup Boundaries

Movi now keeps runtime cleanup on four separate rails so a small cache cleanup never turns into a destructive workspace reset or an accidental Docker-wide prune.

- **Repo-local residue**: use `bash tooling/cleanup/prune_repo_runtime.sh` when you only want to trim repo-side runtime noise such as `.runtime-cache` and forbidden residue under the checkout.
- **Machine cache**: use `bash tooling/cleanup/prune_machine_cache.sh --safe` for the lowest-risk cleanup, `--rebuildable` for governed host caches, or `--aggressive-host` when you intentionally want to reclaim the host-side fallback venv under `~/.cache/movi-organizer`.
- **Docker runtime**: use `bash tooling/cleanup/prune_docker_runtime.sh --dry-run` to audit the container-first runtime surface, `--rebuildable` to prune repo-related build cache, and `--aggressive` only when you explicitly mean to consider current image or named volumes.
- **Destructive workspace reset**: `bash tooling/runtime/runtime_reset.sh --confirm-workspace-reset` is intentionally separate because it also clears workspace `.movi` state. Treat it like resetting a workbench, not like emptying a cache folder.

Container-first default:

- The canonical runtime lane is Docker-backed (`movi-ci:local` plus `movi-web-stack_*` volumes).
- The host-side governed venv under `~/.cache/movi-organizer/venv/default` is treated as a rebuildable fallback surface, not the long-term primary runtime asset.

## Contributing, Support, And Security

- Contribution rules: [CONTRIBUTING.md](CONTRIBUTING.md)
- Support routing: [SUPPORT.md](SUPPORT.md)
- Security reporting: [SECURITY.md](SECURITY.md)
- Questions and ideas: [GitHub Discussions](https://github.com/xiaojiou176-open/movi-organizer/discussions)
- License: [LICENSE](LICENSE)

If review-first cleanup is the workflow you keep wishing existed, star the repo so you can find Movi again when the next messy folder lands.

## Proof And Truth Routes

- Public-facing proof map: [docs/public_proof.md](docs/public_proof.md)
- Detailed operator route: [docs/usage.md](docs/usage.md)
- Architecture and execution boundaries: [docs/architecture.md](docs/architecture.md)
- Public release and platform boundary: [docs/open_source_runbook.md](docs/open_source_runbook.md)
- Third-party notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

Delivery-complete truth for the current snapshot still depends on fresh gate evidence, not on static prose.
Treat `bash tooling/gates/quality_gate.sh` as the delivery-complete receipt for the current snapshot, and treat repository docs as guidance rather than a live platform dashboard.

## Minimal Truth Routes

If you only want the shortest honest map of what is true right now, follow these four routes:

- **Public proof map**: [docs/public_proof.md](docs/public_proof.md)
- **Current release and platform boundary**: [docs/open_source_runbook.md](docs/open_source_runbook.md)
- **Detailed operator route**: [docs/usage.md](docs/usage.md)
- **System wiring and contracts**: [docs/architecture.md](docs/architecture.md)

Public readiness gates:

- `bash tooling/gates/public_readiness_gate.sh repo`
- `bash tooling/gates/public_readiness_gate.sh release`

<!-- BEGIN GENERATED: root-release-identity -->
> Auto-generated: the current source package version comes from `pyproject.toml`. `current-head release` boundaries depend on local/CI runtime evidence, and a clean checkout does not carry a repo-local release evidence summary by default.

- **Current source package version**: `4.0.5`
- **Current current-head release tag**: `v4.0.5`
- **Current current-head release boundary**: `requires_local_release_evidence`
- **Current release publish status**: `unknown in clean checkout`
- **How to read this**: run `npm run release:truth`, then read `current_head_release_truth.status` before making current-head release claims.
- **Verified published closure**: only `published_release_verified` can be described as a verified published closure.
<!-- END GENERATED: root-release-identity -->

<!-- BEGIN GENERATED: root-runtime-topology -->
> Auto-generated: runtime services, default ports, runtime paths, and entrypoint facts live in [generated runtime topology](docs/reference/runtime_topology.generated.md).

- **Compose services**: `movi-ci`, `movi-web-api`, `movi-webui`
- **Web API bind**: `loopback:18080`
- **WebUI bind**: `loopback:5173`
- **Persistent workspace docs alias**: `<workspace-root>`
- **Repo-local cache docs alias**: `<repo-runtime-cache>`
<!-- END GENERATED: root-runtime-topology -->

<!-- BEGIN GENERATED: root-web-api-routes -->
> Auto-generated: current Web API facts come from `contracts/api/web_api.openapi.yaml`; the full method/path list lives in [generated reference](docs/reference/web_api_routes.generated.md).

- **Jobs / history**: `/api/jobs`, `/api/jobs/history`, `/api/jobs/stream`, `/api/jobs/{job_id}`, `/api/jobs/{job_id}/review-queue`, `/api/jobs/{job_id}/review-queue/batch-triage`, `/api/jobs/{job_id}/review-rules/apply`, `/api/jobs/{job_id}/review-rules/from-examples`, `/api/jobs/{job_id}/review-rules/preview`
- **Job events**: `/api/jobs/{job_id}/events`, `/api/jobs/{job_id}/events/stream`, `/api/jobs/{job_id}/stream`
- **Manifest operations**: `/api/jobs/{job_id}/manifest`, `/api/jobs/{job_id}/manifest/batch`, `/api/jobs/{job_id}/manifest/conflicts`, `/api/jobs/{job_id}/manifest/conflicts/resolve`, `/api/jobs/{job_id}/manifest/rows/{row_id}`, `/api/jobs/{job_id}/manifest/view`, `/api/jobs/{job_id}/manifest/{row_id}/preview`
- **Job actions**: `/api/jobs/analyze`, `/api/jobs/apply`, `/api/jobs/rollback`, `/api/jobs/{job_id}/cancel`, `/api/jobs/{job_id}/retry`
- **Report / audit**: `/api/jobs/{job_id}/audit`, `/api/jobs/{job_id}/report`
- **Preferences**: `/api/preferences/learned-rules`, `/api/preferences/naming-templates`, `/api/preferences/review-rules`, `/api/preferences/runtime`, `/api/preferences/runtime/validate`, `/api/preferences/strategy-packs`, `/api/preferences/views`, `/api/preferences/watch-sources`
- `overlay` / `resolved snapshot` are internal model and file-output concepts, not stable public HTTP routes.
<!-- END GENERATED: root-web-api-routes -->

<!-- BEGIN GENERATED: root-ci-governance-summary -->
> Auto-generated: CI truth-chain, failure-domain policy, navigation entrypoints, and executable gate facts come from [required checks matrix](docs/required_checks_matrix.md), [runner contract](docs/runner_contract.md), and [ci.yml](.github/workflows/ci.yml).

- **Canonical truth path**: `build-ci-image -> change-detection -> {webui-build-test, quality-gate-full} -> functional-gate -> test`
- **Canonical gate**: `quality-gate-full`
- **Supplemental gates**: `webui-build-test` (frontend correctness), `functional-gate` (critical smoke), `test` (Python version parity)
- **Dual failure-domain required jobs**: None
- **Shared-pool-only required jobs**: None
- **Side workflows**: `pre-commit` bootstraps directly on hosted runners, while `live-integration` and `mutation-manual` reuse `reusable-build-runtime-image.yml`; runtime image build keeps provenance artifact wiring when the platform supports attestations.
- **Drift / evidence surfaces**: `nightly-drift-audit.yml`, `collect_ci_run_metrics.py`, `generate_ci_evidence_bundle.py`.
- **Local auxiliary evidence**: `npm run ci:local` writes repo-local CI metrics, a repo-local evidence bundle, and governed upstream receipts under the repo-local runtime cache directory; these are local derived reports, not Branch Protection truth. Read `truth.truth_class`, `truth.remote_traceability`, and `truth.authoritative_terminal_receipt` before treating the bundle as anything stronger. Older pass receipts remain historical audit evidence only; current closeout wording must follow the latest canonical terminal receipt.
- **Developer fallback**: use `bash tooling/gates/pre_push_gate.sh` (`standard/strict/full`) for fast local feedback before remote CI.
<!-- END GENERATED: root-ci-governance-summary -->
