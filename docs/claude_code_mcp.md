---
title: Fileman MCP For Claude Code
description: Wire Fileman MCP v1 into Claude Code when you want local-first review-safe file organization with MCP instead of direct file mutation.
---

## Fileman MCP For Claude Code

Fileman already has a real Claude Code story today:

- **Category**: review-first local AI file organizer
- **Hotness hook**: stdio-first MCP for Claude Code
- **Outcome**: let Claude Code help with manifest review, rule drafting, and dry-run previews while keeping real execution behind the same human review boundary

In plain language: Claude Code can help with the planning desk, but it still does not get to walk into the warehouse and move boxes on its own.

## Why Claude Code Is A Real Fit

Claude Code is a good current fit because Fileman already ships:

- a **local-first** stdio MCP server
- review-safe tools that mirror the current app workflow
- no direct file-move shortcut for agents
- allowlisted docs resources so an agent can read the safety rules before acting

This is not “future roadmap” wording. It is the current shipped MCP boundary.

## Current Best Uses

Use Claude Code with Fileman when you want it to:

- inspect a messy batch before creating work
- read review queues, reports, and manifests
- draft overlay-safe edits
- preview reusable rules before applying them to the overlay
- queue a dry-run apply preview for a human to inspect later

## Current Non-Goals

Do **not** describe the current Claude Code integration as:

- a hosted API platform
- autonomous file organization
- agent-driven execute mode
- a backdoor around `apply`

`apply.execute` is intentionally absent from `Fileman MCP v1`.

## Minimal Wiring

Claude Code already exposes a first-party MCP management command, so the shortest current route is:

```bash
claude mcp add fileman -- bash /absolute/path/to/fileman/tooling/runtime/run_mcp_stdio.sh
```

If you want to inspect or remove the entry later:

```bash
claude mcp list
claude mcp remove fileman
```

If your Claude Code setup wants the raw stdio shape instead of the helper command, the portable core is:

```json
{
  "name": "fileman",
  "command": "bash",
  "args": ["/absolute/path/to/fileman/tooling/runtime/run_mcp_stdio.sh"]
}
```

If you prefer an installed entrypoint, use `fileman-mcp` when it is available in your environment.

## What To Read Next

- [Fileman MCP v1](./mcp.md)
- [Developer And Agent Guide](./developer_guide.md)
- [Review-First AI File Organizer](./review_first_ai_file_manr.md)
