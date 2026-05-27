# AGENTS.md

This file defines repository-wide execution constraints for coding agents in this repository.

## 1. Goal and Boundary

- Goal: keep the repository safe, auditable, and executable for `analyze`, `apply`, `rollback`, and `report`.
- Boundary:
  - This file is the repository governance and safety policy.
  - `CLAUDE.md` is the execution-memory companion file.
  - When they disagree, safety and process rules in this file win.

## 2. Priority and Conflict Resolution

- Order of precedence:
  - system instructions
  - developer instructions
  - nearest `AGENTS.md`
  - nearest `CLAUDE.md`
  - README and ordinary docs
- When same-level guidance conflicts, prefer the safer and more reversible path.

## 3. Hard Standards

Every future change must preserve these standards:

1. Live tests must be real when the path is declared live.
2. Lint errors must block before merge.
3. Unit tests must be real, with repository coverage floors enforced by the gate stack.
4. Placebo assertions are forbidden.
5. Parallelizable checks should run in parallel when safe.
6. Long-running checks must emit clear heartbeats.
7. Run short checks before long checks.
8. Code and docs must stay bidirectionally aligned.
9. Root and major modules must keep `AGENTS.md` and `CLAUDE.md`.
10. Atomic-commit gates must stay enforced in pre-push and CI.

Major modules currently include:

- `packages/application`
- `packages/domain`
- `packages/infrastructure`
- `packages/observability`
- `tests`
- `tooling`
- `docs`
- `apps/webui`

## 4. Repository Facts

- Main code roots: `apps/`, `packages/`, `tooling/`, `tests/`, `docs/`
- Core modules: `packages/application/`, `packages/domain/`, `packages/infrastructure/`, `packages/observability/`
- Tests: `tests/unit/`, `tests/integration/`, `tests/e2e/`
- Tooling public entry roots: `tooling/runtime/`, `tooling/gates/`, `tooling/docs/`, `tooling/cleanup/`, `tooling/ci/`, `tooling/upstreams/`
- WebUI module: `apps/webui/`
- CI source of truth: `.github/workflows/ci.yml`
- Python project file: `pyproject.toml`
- Config example: `contracts/runtime/config.example.toml`
- Architecture doc: `docs/architecture.md`

## 5. Runtime and Tooling

- Python `>=3.10`
- Package/runtime stack: `pip` + `venv`
- Core dependencies: `google-genai`, `Pillow`, `PyYAML`
- Quality tools: `pytest`, `ruff`, `mypy`, `bandit`, `pip-audit`, `pre-commit`
- Public shell entrypoints live under `tooling/runtime|gates|docs|cleanup|ci|upstreams`

## 6. Navigation

- Root governance: `AGENTS.md`, `CLAUDE.md`
- Core code: module-level `AGENTS.md` / `CLAUDE.md` under `packages/`
- Tests: `tests/AGENTS.md`, `tests/CLAUDE.md`
- Tooling: `tooling/AGENTS.md`, `tooling/CLAUDE.md`
- Docs: `docs/AGENTS.md`, `docs/CLAUDE.md`
- WebUI: `apps/webui/AGENTS.md`, `apps/webui/CLAUDE.md`

## 7. Standard Commands

Run from the repository root unless noted otherwise:

```bash
bash tooling/runtime/bootstrap_env.sh
bash tooling/gates/quality_gate.sh
bash tooling/gates/pre_push_gate.sh
bash tooling/gates/secret_scan.sh .
bash tooling/docs/docs_smoke.sh --install-smoke
~/.cache/fileyard/venv/default/bin/pre-commit install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
```

CI chain role notes:

- `quality-gate-full` is the canonical full-verification job
- `webui-build-test` is the frontend correctness job
- `functional-gate` and `test` provide additional signal, not a second truth source

## 8. Workflow Rules

1. Read before editing.
2. Search for reuse before writing.
3. Prefer the smallest viable change.
4. Run targeted verification first, then broader gates if needed.
5. Fix root causes instead of skipping checks.
6. Report with evidence: changed files, commands, results, remaining gaps.

## 9. Code and Change Rules

- Keep changes scoped to the task.
- New Python code should include types where practical.
- Do not commit zombie code.
- Do not leave temporary debug logic in the main path.
- Do not add compatibility shims just to hide the real issue.

## 10. Safety Rules

- Never commit secrets, tokens, or private credentials.
- Do not run destructive commands without explicit authorization.
- `apply` must stay behind dry-run and manifest validation.
- `rollback` must stay bounded by `--allowed-root`.
- Host-process safety is a hard boundary:
  - do not add `killall`, `pkill`, `killpg(...)`, negative/zero PID signals,
    `osascript`, `System Events`, `loginwindow`, or Force Quit APIs to tracked
    automation
  - cleanup must stay exact-scope and repo-owned; do not borrow broad
    host-cleanup shortcuts
  - detached browser or runtime launch flows must require explicit operator
    acknowledgement or a provable repo-owned runtime lane

## 10.1 Host Safety Contract

- `worker-safe` is the default mode for this repository.
- `killall`, `pkill -f`, pattern-scoped force-kill, and broad host cleanup are forbidden in first-party automation paths.
- Process teardown must stay on exact, repo-owned pid handles or recorded child processes; if ownership cannot be proven, fail closed.

## 11. Key References

- Architecture: `docs/architecture.md`
- Usage: `docs/usage.md`
- CI truth: `.github/workflows/ci.yml`
- Logging policy: `docs/logging_observability.md`

## 12. No Logs No Merge

Critical paths must emit structured logs.

Required fields include:

- `timestamp`
- `level`
- `event`
- `trace_id`
- `module`
- `action`
- `status`
- `duration_ms`

Never log raw secrets, credentials, or private local paths.
