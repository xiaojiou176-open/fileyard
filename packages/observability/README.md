# packages/observability

This is the observability layer.

## Responsibilities

- structured logs
- correlation identifiers
- run bundle output
- evidence and event data structures

## Boundary

- record facts
- do not change business outcomes
- reuse the shared `run_id` / `trace_id` / bundle model
