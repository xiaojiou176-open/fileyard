# CLAUDE.md (mcp)

Quick execution memory for `apps/mcp/`.

## Focus

- MCP is a thin facade over the current review-first workflow
- Tools may inspect, draft, and patch overlays, but must not expose direct file-mutation shortcuts
- v1 should stay stdio-first and local-first

## Main files

- `apps/mcp/service.py`
- `apps/mcp/server.py`
- `tooling/runtime/run_mcp_stdio.sh`

## Main checks

```bash
~/.cache/fileman/venv/default/bin/python -m pytest -q -o addopts='' tests/unit/test_mcp_server.py
bash tooling/runtime/run_mcp_stdio.sh --help
```
