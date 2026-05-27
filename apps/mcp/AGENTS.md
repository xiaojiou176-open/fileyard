# AGENTS.md (mcp)

Local policy for `apps/mcp/`.

## Goal

Expose Fileman to MCP clients through a thin, local-first facade that keeps the existing review-first safety model intact.

## Rules

- Reuse existing Web API or application semantics before adding new service logic.
- Prefer stdio/local-first transport for v1.
- Do not expose shortcuts that bypass review, dry-run, or rollback boundaries.
- Keep stdout reserved for the MCP protocol. Operational logs must stay on stderr.
