# AGENTS.md (application)

This directory holds the orchestration layer for `analyze`, `apply`, `rollback`, and `report`.

## Boundary

- Orchestrate use cases
- Do not create new repository or CI truth sources here
- Keep `run_id`, structured logging, and run-bundle semantics aligned
