# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (Unreleased)

- No unreleased changes yet.

## [4.0.5] - 2026-03-27

- Live browser target stability: aligned the default real-site probe target with `https://docs.github.com/en` for local gates and CI smoke preflight so GitHub-hosted browser checks use a faster, platform-local public page instead of the slower IANA route that timed out on hosted live runs.
- Live browser contract: narrowed the third-party external probe to browser egress plus successful HTML response semantics, so hosted live no longer treats a public site's DOM attach timing as a repository blocker.
- Live diagnostics: `run_live_tests.sh` now keeps per-attempt log/JUnit artifacts and forces unbuffered pytest output so hosted live failures no longer collapse into an empty final log artifact.
- Live WebUI host routing: aligned the hosted live browser path with the non-live WebUI E2E route by keeping the static app host on `127.0.0.1`, avoiding `localhost`-specific resolution differences on GitHub-hosted runners.
- Live WebUI route entry: aligned the hosted live journey with the stable non-live path by entering `/app/` first and navigating to Analyze through the dashboard instead of deep-linking straight to `/app/analyze`.
- Live WebUI navigation readiness: switched hosted live app-route navigations to commit-level page entry and kept feature-level readiness checks on visible UI landmarks, reducing dependence on `domcontentloaded` timing inside the hosted browser lane.
- Live WebUI helper parity: reused the non-live dashboard retry/readiness pattern in the hosted live E2E so loopback variants and dashboard anchors are probed before the flow enters Analyze.
- Live WebUI CI browser launch: aligned the hosted live browser startup with a more CI-friendly Chromium argument set and added an explicit static `/app/` readiness check before the browser enters the dashboard.
- Live workflow execution lane: restored the manual `live-integration` WebUI/browser lane to `ubuntu-latest` after fresh shared-pool evidence showed the amd64 live image still closing Playwright Chromium on arm64 hosts even after browser-level retry hardening.
- Live external browser retry path: the real-site Playwright probe now treats unexpected closed-browser/context failures as transient browser instability and relaunches a fresh Chromium instance for each retry attempt instead of reusing a possibly-dead browser process.
- Live WebUI hosted browser parity: the hosted live WebUI path now prefers the same WebKit-first browser strategy as the stable non-live WebUI E2E and pre-installs both `webkit` and `chromium` browser bundles before the live suite starts.
- Live WebUI hosted browser selection: the live WebUI lane now prefers Chromium first when running under CI/hosted automation, only falling back to WebKit when Chromium launch is unavailable, so hosted runs no longer depend on a browser family that has not yet been proven stable in that lane.
- Live browser cache hygiene: `run_live_tests.sh` now installs its Playwright browser bundles into an isolated live-only cache directory so real live verification no longer bloats the governed machine-cache surface and trips unrelated cache-size gates afterward.
- Mutation canary local gate isolation: `quality_gate` now runs the mutation canary against a temporary repo snapshot instead of mutating the bind-mounted working tree in place, avoiding stale source/cache bleed between `pytest-fast` and later canary cases on local containerized runs.
- Live workflow closeout: `live-integration` now pulls the private `fileorganize-ci` GHCR image with `GHCR_PUSH_TOKEN` and a `github.token` fallback, matching the working CI pull posture instead of relying on the `github.token`-only path that returned `403 Forbidden` on the self-hosted live lane.
- Live browser stability: moved the manual `live-integration` execution lane onto `ubuntu-latest` so the amd64 runtime image no longer runs Playwright Chromium under arm64 qemu emulation on the shared pool.
- Live timeout budget: widened the manual `live-integration` job timeout and `LIVE_MAX_DURATION_SECONDS` so the hosted live suite can finish or fail inside the wrapper budget instead of being hard-cancelled by the job wall clock first.

## [4.0.4] - 2026-03-26

- Live workflow hardening: switched the `live-integration` runtime-image pull path back to `github.token` / `github.actor` so CI hardening no longer rejects the workflow for referencing `GHCR_PUSH_TOKEN`.
- Live browser stability: guarded the external-site Playwright test so context teardown no longer crashes with `TargetClosedError` after the browser closes unexpectedly during retries.
- Packaging stability: aligned `tooling/requirements-dev.lock.txt` with the runtime lock for shared transitive dependencies (`anyio`, `cryptography`) so `pip install -r tooling/requirements.lock.txt -r tooling/requirements-dev.txt` no longer hits version conflicts.

## [4.0.3] - 2026-03-26

- Release alignment: advanced the stable source version to `4.0.3` so current-head release truth no longer reuses the already-published `v4.0.2` assets that point at the older `498dd73` snapshot.
- CI runtime image publishing: kept GHCR authentication state available across workflow steps and removed the provenance push-to-registry requirement from the canonical CI path, allowing `build-ci-image` to pass on the current GitHub Actions runner behavior.
- WebUI runtime resilience: `tooling/runtime/run_webui_task.sh` now permits explicit host execution only outside CI, retries dependency installation after clearing broken `node_modules` residue, and safely handles empty forwarded npm arguments under `set -u`.
- Live WebUI coverage: refreshed the live Playwright selectors to match the current English-first Analyze and Jobs surfaces while keeping the manifest page expectation aligned with the current heading.
- Local-only governance: root change-control contracts now classify repo-root `.env` as a must-remain-untracked local-only surface so secret-bearing operator convenience files cannot drift into tracked public state.

## [4.0.2] - 2026-03-26

- Storefront: added a 10-second tour panel and a before/after comparison to the README so first-time visitors get visual proof before deep operator detail.
- Release surface: front page navigation now links directly to GitHub Releases alongside docs, discussions, and security.
- Release truth: advanced the source release line to `4.0.2` so current-head evidence can close on the stable `v4.0.2` release instead of the earlier RC tags.
- Runtime governance: split disk maintenance into repo-local residue, machine cache, workspace evidence, and shared runner workdir lanes with dedicated public entrypoints.
- Quality gate bootstrap: prebuilt runtime venv restoration now uses a shared restore helper for host/container paths instead of relying on `cp -a` into an already-mounted destination.
- Open source readiness: added MIT licensing metadata, public support/security/contribution boundaries, CODEOWNERS, issue/PR templates, and an explicit GitHub Releases-oriented runbook.
- Open source release closeout: release draft generation and runbook now record current private-repo platform gaps explicitly, including visibility switch, branch protection limits, and `SECURITY.md` fallback when Private Vulnerability Reporting is unavailable.
- Evidence lanes: added governed history secret scanning under `.runtime-cache/logs/security/` and hardened CI evidence bundle collection to consume explicit governed runtime roots instead of loose fallback paths.
- AI quality evidence: added a minimum AI eval pack with offline golden coverage, synthetic audio contract coverage, and a live rubric lane that reports explicit skipped/N/A without credentials.
- Quality gates: `quality_gate.sh` now writes the only coverage truth from the full non-live suite, and containerized bootstrap installs hash-locked base requirements separately from unhashed dev extras.
- Frontend gates: `lint_frontend.sh` now treats missing/blocked Gemini access as explicit local skips while keeping CI fail-closed, and `gemini_ui_ux_audit.py` batches all frontend files instead of truncating at 20.
- WebUI: aligned Vite build output with `/app/` static hosting, added route/base-aware router mounting, and hardened WebUI API wiring for SSE, manifest overlay/conflicts, preview fallback, saved views, and naming templates.
- Web stack: added one-command local/compose startup flows for Web API + WebUI (`run_web_api.sh`, `run_webui.sh`, `run_web_stack.sh`) and expanded `docker-compose.yml` with `fileorganize-web-api` / `fileorganize-webui`.
- Tests: expanded `tests/unit/test_web_api.py` coverage for jobs SSE, preview payloads, and WebUI-style rollback request fields.
- Docs: documented newly added `Web API + WebUI` startup flow in `README.md` and `docs/usage.md`, including `/app` static hosting and `/api/jobs/*` endpoints.
- Docs: added WebUI V2 documentation in `README.md` and `docs/usage.md` for SSE real-time task flow, manifest `overlay/resolved snapshot` model, jobs history, saved views, naming templates, rollback audit, and V2 endpoint families (`events/stream`, manifest overlay/resolved, views, naming templates, rollback audit).
- CI: moved heavy verification workflows onto `self-hosted` + `shared-pool` while keeping bootstrap/image lanes on `ubuntu-latest`, so the closeout story matches the current workflow topology.
- Security gates: added an explicit `pip_audit_allowlist` contract for dev-lock-only accepted risks when upstream has not published a patched dependency release yet.
- CI: added `runner-bootstrap` gate in `.github/workflows/ci.yml` to validate organization-level shared runner inventory with strict set equality for the approved shared runner names and online status.
- CI: updated `runner-bootstrap` inventory to the current shared runner topology: `pool-core01-*` + `pool-core02-*` + `pool-core03-*` + `pool-core04-*` + `pool-core05-*`; old `pool-spot01-*` / `pool-spot02-*` names are no longer accepted.
- Tooling: moved pre-commit's Node-based markdown/style lint hooks onto system `node`/`npx`, avoiding self-hosted `pre-commit` `node_env` failures caused by missing `libatomic.so.1`.
- Tooling: updated `tooling/scripts/check_ci_workflow_hardening.py` to enforce `shared-pool` runner labels, block runner registration commands in repo workflows (`config.sh` / `./run.sh` / `remove.sh`), and require `runner-bootstrap`.
- Reliability: hardened `tooling/scripts/secret_scan.sh` with a git-index fallback path when full-tree `rg` scanning returns infrastructure-level errors in containerized environments.
- Reliability: hardened `tooling/scripts/run_live_tests.sh` to always ensure Playwright Chromium binaries are installed before live browser tests, preventing stale-cache false negatives.
- Ops: refreshed repository secret `ORG_RUNNER_AUDIT_TOKEN` with org-runner read permission to unblock `runner-bootstrap` strict inventory validation in CI.
- CI: tag-push commit-range gates now recognize release tags as empty-range-allowed events instead of treating stable/published tags as commit-governance failures.
- CI: default merge-time flow no longer schedules nightly full CI or nightly live integration runs, and live smoke preflight now degrades to an explicit non-blocking skip when live secrets are not configured.

## [4.0.0] - 2026-03-03

### test

- ci: extended the weekly mutation lane to the `reporting` module, pinned `mutmut==2.4.4`, and added cache-hit version validation to avoid silent drift.
- test: strengthened e2e and gatekeeper fixtures and unified the `FILEORGANIZE_ALLOW_HOST_EXECUTION=1` execution rule so the suite stays stable under strict environment gates.

### Added

- README: added a one-command `pre-commit` setup section with three hook types (`pre-commit`, `pre-push`, `commit-msg`) and first full-run commands.
- README: added layered governance documentation for `local gates` vs `CI red lines`, aligned with `.github/workflows/ci.yml`.
- CHANGELOG: initialized Keep a Changelog structure for ongoing release notes governance.
- Dependencies: normalized `requirements.lock.txt` and `requirements-dev.txt` ordering via pre-commit `requirements-txt-fixer`.
- Scripts: added `tooling/scripts/check_cli_perf_baseline.sh` for executable CLI performance budget evidence (`cli.report.duration_ms`).
- Scripts: added `tooling/scripts/check_rollback_rto.sh` for executable rollback RTO baseline evidence (`cli.rollback.dry_run.duration_ms`).
- Scripts: added `tooling/scripts/check_observability_baseline.sh` for executable observability triad evidence (`SLI/SLO + Tracing + Alerting`).
- Docs: added a dedicated major-release migration narrative for breaking changes and N-1 manifest evidence sources.

### Changed

- Hygiene: hardened `.gitignore` for runtime/test artifacts and local residue (`cache/`, `logs/`, `.coverage.*`, `htmlcov/`, `.hypothesis/`, `.tox/`, `.nox/`, notebook checkpoints, patch residue), while explicitly keeping `.env.example` trackable.
- Dependencies: fixed lockfile compatibility by aligning `pydantic-core` with pinned `pydantic==2.12.5` in `requirements.lock.txt`, restoring strict gate stability (`placebo-assertion-gate` and pre-commit dependency bootstrap).
- Tooling: refreshed frozen `pre-commit` hook revisions in `.pre-commit-config.yaml` via `pre-commit autoupdate --freeze` to satisfy `check-pre-commit-outdated` pre-push gate.
- Tooling: refreshed frozen `typos` hook revision in `.pre-commit-config.yaml` (`e1f6f6e...` -> `v1`) to keep local/CI hooks aligned with `check-pre-commit-outdated`.
- CI: `pre-commit` workflow now bootstraps the canonical runtime venv before `pre-commit/action`, so strict local hooks remain enforced in GitHub-hosted checks.
- CI: tightened `lint_frontend.sh` to fail-closed when frontend sources exist but `GEMINI_API_KEY` is missing; Gemini semantic audit is now mandatory in that case.
- CI: isolated heavy-job routing to `e2-core-dedicated` to avoid accidental scheduling on `spot` runners sharing `e2-core` label but lacking required docker-compose dependencies.
- CI: moved core gate workflows (`ci`, `pre-commit`, `live-integration`, `mutation-weekly`) onto `e2-core-dedicated` to avoid GitHub-hosted quota depletion causing false-negative gate failures.
- CI: fixed `secrets-supply-chain-gate` Python bootstrap on self-hosted runners by adding `setup-python` and using `python -m pip`/`python -m detect_secrets` instead of relying on system `python3` pip availability.
- CI: added `pre-commit` hosted->self-hosted fallback chain. Workflow now prefers GitHub-hosted execution and auto-falls back to `e2-core-dedicated` only when hosted jobs fail before entering execution (quota/scheduler class), while preserving hard failure on real lint/test violations.
- CI: extended hosted->self-hosted fallback to `ci.yml` lightweight gates (`change-detection`, `commit-message-lint`, `atomic-commit-gate`, `secrets-supply-chain-gate`, `ci-hardening-gate`) while preserving original required-check job IDs and strict fail-closed behavior for real gate failures.
- CI: routed all heavy workflows/jobs to `[self-hosted, e2-core]` so Core + Spot (5 Google Cloud runners) share high-load execution, while lightweight gates remain GitHub-hosted-first with fallback.
- CI: hardened semantic UI/UX gate to fail when frontend files exist but `GEMINI_API_KEY` is missing (no silent skip on CI).
- CI: hardened live-integration and live test runner to require explicit `GEMINI_API_KEY` + `GEMINI_MODEL` + `FILEORGANIZE_LIVE_TEST_URL` (no default model/URL fallback).
- Tooling: `sync_github_actions_secrets.sh` now fails-fast if required secrets are absent in `.env` instead of skipping missing keys.
- Tooling: clarified local pre-push default is `standard` mode (`fast-lane -> changed-only secret scan -> tracked-tests-integrity -> atomic-commit -> commit-message`); `strict/full` remain optional for deeper local verification.
- Release audit policy: clarified CLI scoring path where `CWV/RUM` is `N/A` (non-blocking), replaced by executable CLI performance baseline + rollback RTO baseline checks.
- Observability policy: promoted observability triad baseline (`SLI/SLO + Tracing + Alerting`) to executable release evidence with JSON artifact output.

### Breaking (4.0.0 major release)

- `rollback` requires `--allowed-root`; strict integrity verification is default-on (`--strict-integrity`).
- `apply --trust-manifest-input-root` requires paired `--manifest-input-root-allowlist`.
- Unknown config keys and invalid config value types fail fast (`CONFIG_UNKNOWN_KEY` / `CONFIG_TYPE_INVALID`).

### Migration

- Follow the release runbook and the executable release evidence surfaces for step-by-step migration and release evidence.
- N-1 manifest compatibility evidence source:
  - `~/.cache/fileorganize/venv/default/bin/python -m pytest -q tests/e2e/test_apply_schema_newer_warning.py`
  - `~/.cache/fileorganize/venv/default/bin/python -m pytest -q tests/unit/test_manifest_store_writer_and_schema_versions.py`

- Ops: retried CI execution due to transient GitHub Actions scheduler instability (no functional code change).
