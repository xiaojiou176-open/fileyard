# tests

This directory is the repository quality layer.

## Structure

- `tests/unit/`: fine-grained contract and helper behavior
- `tests/integration/`: cross-module offline flows
- `tests/e2e/`: real entry-surface flows
- `tests/fixtures/`: synthetic inputs and expected outputs

## Boundary

- Tests must block bad logic, not decorate it.
- Legacy-only text belongs in fixtures, not in production surfaces.
