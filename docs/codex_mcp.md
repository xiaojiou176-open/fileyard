---
title: Fileman MCP For Codex
description: Wire Fileman MCP v1 into Codex when you want review-first file organization without giving an agent a direct execute shortcut.
---

## Fileman MCP For Codex

Fileman already has a real Codex-friendly story today:

- **Category**: review-first local AI file organizer
- **Hotness hook**: stdio-first MCP for Codex
- **Outcome**: let Codex inspect jobs, review queues, manifests, and dry-run previews without giving it a secret file-move shortcut

In plain language: Codex can help you understand and edit the plan, but it still cannot skip the same review-first safety gate a human uses.

## Why Codex Is A Real Fit

Codex is a good fit for Fileman right now because the repo already ships these real pieces:

- `Fileman MCP v1` as a **stdio-first** local integration surface
- review-safe tools for `analyze.create`, `review_queue.get`, `manifest.get`, `manifest.patch_*`, `review_rule.*`, and `apply.preview`
- read-only docs and workflow resources that explain the current safety boundary

That means Codex is not being name-dropped as a fantasy partner. The connection exists because the MCP surface already exists.

## What Codex Can Safely Do Today

Use Codex with Fileman when you want it to:

- inspect current runtime settings before creating work
- launch a local analyze draft for a batch
- read the review queue and copilot summary
- patch manifest rows through the overlay only
- preview review rules and apply them to the overlay
- queue a dry-run apply preview

Think of it like asking a careful assistant to prepare the checklist, not giving that assistant the keys to drive the moving truck.

## What Codex Cannot Do Today

Fileman does **not** currently let Codex:

- call a hidden `apply.execute`
- move or rename files without review
- bypass `overlay -> resolved snapshot -> dry-run -> execute`
- act like a hosted remote automation platform

## Minimal Wiring

Codex already ships a first-party MCP command surface, so the shortest current route is:

```bash
codex mcp add fileman -- bash /absolute/path/to/fileman/tooling/runtime/run_mcp_stdio.sh
```

If you want to inspect the saved MCP configuration or remove it later:

```bash
codex mcp list
codex mcp remove fileman
```

The portable core is still just a stdio command. If you are wiring Fileman into a Codex client surface that wants JSON instead of the CLI helper, use:

```json
{
  "name": "fileman",
  "command": "bash",
  "args": ["/absolute/path/to/fileman/tooling/runtime/run_mcp_stdio.sh"]
}
```

If you install the Python package entrypoint, `fileman-mcp` can be used instead of the shell wrapper.

## What To Read Next

- [Fileman MCP v1](./mcp.md)
- [Developer And Agent Guide](./developer_guide.md)
- [Detailed Operator Guide](./usage.md)
