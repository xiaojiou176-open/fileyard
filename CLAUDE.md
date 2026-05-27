# CLAUDE.md

Execution memory for Claude/Codex in this repository.

Read `AGENTS.md` first for repository-wide safety and governance rules.

## 1. Project Context

- Project type: manifest-driven media organizer
- Core flow:
  - `analyze`
  - `apply`
  - `rollback`
  - `report`
- Main implementation roots:
  - `packages/application/`
  - `packages/domain/`
  - `packages/infrastructure/`
  - `packages/observability/`
- Main entrypoints:
  - `apps/cli/fileman.py`
  - `apps/cli/cli_app.py`
  - `apps/api/web_api.py`

## 2. Navigation

- Root policy: `AGENTS.md`
- Root execution memory: `CLAUDE.md`
- Core modules: module-level `AGENTS.md` / `CLAUDE.md` under `packages/`
- Tests: `tests/AGENTS.md`, `tests/CLAUDE.md`
- Tooling: `tooling/AGENTS.md`, `tooling/CLAUDE.md`
- Docs: `docs/AGENTS.md`, `docs/CLAUDE.md`
- WebUI: `apps/webui/AGENTS.md`, `apps/webui/CLAUDE.md`
- Logging policy: `docs/logging_observability.md`

## 3. Fast Commands

```bash
bash tooling/runtime/bootstrap_env.sh
bash tooling/gates/quality_gate.sh
bash tooling/gates/pre_push_gate.sh
bash tooling/gates/secret_scan.sh .
bash tooling/docs/docs_smoke.sh --install-smoke
```

Business entrypoints:

```bash
bash tooling/runtime/run_analyze.sh
bash tooling/runtime/run_apply.sh
bash tooling/runtime/run_rollback.sh
bash tooling/runtime/generate_report.sh
```

## 4. Working Rules

- Read first, edit second.
- Search for reuse before adding new code or tests.
- Prefer public tooling entrypoints over internal script paths.
- Run targeted verification before broad gates.
- Fix root causes instead of weakening checks.

## 5. Module Reminders

- `packages/application/`: orchestration only
- `packages/domain/`: rules and contracts only
- `packages/infrastructure/`: I/O and provider adapters
- `packages/observability/`: logs, bundles, traceability
- `tests/`: unit, integration, e2e
- `tooling/`: public command surface and gate surface

## 6. Definition of Done

Default done signal:

- targeted tests pass
- required gates pass
- docs stay aligned
- no secret leakage
- no fake green path
