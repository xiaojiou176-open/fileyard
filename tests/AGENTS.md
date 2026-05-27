# AGENTS.md (tests)

Local policy for `tests/`.

## Goal

Protect the real behavior of `analyze`, `apply`, `rollback`, `report`, and repository gates.

## Rules

- No placebo assertions.
- Live tests must be real when the path is declared live.
- Prefer extending existing fixtures and helpers.
- Add direct coverage for split modules, not only legacy entrypoints.
- Validate structured logging fields, not only plain string fragments, when testing observability.

## Navigation

- `tests/unit/`
- `tests/integration/`
- `tests/e2e/`
- `tooling/gates/test_quality_gate.sh`

## Verification

- Run the smallest relevant test set first.
- Expand to broader gates when the change touches shared contracts or entrypoints.
