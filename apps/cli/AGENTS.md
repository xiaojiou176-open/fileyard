# AGENTS.md (apps/cli)

This directory contains the CLI entry surface only.

## Boundary

- Keep business rules out of the CLI layer.
- Treat `fileman.py` and `cli_app.py` as the canonical CLI entrypoints.
