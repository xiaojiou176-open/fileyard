# AGENTS.md (observability)

This directory holds event logging, run bundles, correlation IDs, and evidence indexing.

## Boundary

- Preserve `run_id`, `trace_id`, and evidence contracts
- Do not move business decisions into logging helpers
