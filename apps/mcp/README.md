# apps/mcp

`apps/mcp` is the runtime implementation path for Fileorganize MCP v1.

The canonical public root for the product still lives at the repo root
(`README.md` + `manifest.yaml`), and the canonical machine-readable descriptor
for the pure-MCP lane now lives at `../../server.json`.

Use the surfaces in this order when you need truthful MCP context:

1. `../../README.md`
   - canonical public storefront and overall product truth
2. `../../server.json`
   - canonical machine-readable MCP descriptor for the repo
3. `../../docs/mcp.md`
   - public MCP support surface, install path, and safety boundary
4. `apps/mcp/*`
   - implementation files for the local stdio facade

In plain language: this directory is the machine room, not the store window.
It explains where the MCP runtime is implemented, but it must not pretend to be
the repo storefront or a live registry listing.

## What lives here

- `server.py`
  - FastMCP entrypoint and tool/resource registration
- `service.py`
  - thin facade over the review-first Fileorganize workflow
- `__main__.py`
  - package entrypoint for local execution

## Truth boundary

- this directory does not claim a live registry listing
- this directory does not replace `docs/mcp.md` as the public MCP support note
- this directory does not bypass the review-first -> dry-run -> execute contract
