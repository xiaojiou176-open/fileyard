---
title: Fileorganize MCP v1
description: Local-first stdio MCP surface for Fileorganize with review-safe tools, read-only resources, and no execute shortcut.
---

## Fileorganize MCP v1

`Fileorganize MCP v1` is the local-first stdio extension surface for Fileorganize.

The canonical public root still lives at the repo root (`README.md` +
`manifest.yaml`), the canonical machine-readable descriptor now lives at
`../server.json`, and `../apps/mcp/README.md` explains the runtime
implementation path. This page explains the pure-MCP support surface; it does
not mean the repo already ships a live registry listing.

The canonical public root still lives at the repo root (`README.md` +
`manifest.yaml`), the canonical machine-readable descriptor now lives at
`../server.json`, and `../apps/mcp/README.md` explains the runtime
implementation path. This page explains the pure-MCP support surface; it does
not mean the repo already ships a live registry listing.

In plain language: it gives an agent or automation client a supervised control window into the same workflow humans use in the app. It can inspect jobs, read reports, patch overlays, preview reusable rules, and queue dry-run-safe follow-up work, but it does not get a secret “move files now” shortcut.

## What V1 Is

- a **stdio-first** MCP server for local clients
- a **thin facade** over the current Fileorganize workflow
- a **review-safe** tool and resource surface
- a **developer and agent integration point** that still respects `overlay-only`, `dry-run before execute`, and `rollback-ready`

## What V1 Is Not

- not a hosted API platform
- not a remote multi-tenant service
- not an autonomous organizer that mutates files without review
- not a second business-logic stack that bypasses the Web API or application layers

Think of it like a supervised service window at the same workshop. The agent can ask for plans, previews, and review data through the window, but it still cannot reach behind the counter and move boxes on its own.

## Run The Server

Repo-local runtime entrypoint:

```bash
bash tooling/runtime/bootstrap_env.sh
bash tooling/runtime/run_mcp_stdio.sh
```

Convenience npm script from the repo root:

```bash
npm run mcp:stdio
```

Quick discovery helpers:

```bash
npm run mcp:tools
npm run mcp:resources
```

Installed Python entrypoint, if you install the package or add the managed venv bin directory to your PATH:

```bash
fileorganize-mcp
```

Both entrypoints are local-first and stdio-first. They are meant to be launched by an MCP-capable client from your machine, not published as a remote hosted endpoint.

## Honest Client Fit Today

If you want the shortest ecosystem answer:

- **Primary current fit**: Codex and Claude Code, because both can use the current stdio-first local MCP surface directly
- **Secondary ecosystem fit**: Cursor and other local MCP-capable clients, because the transport and tool surface already match their integration model
- **Comparison-only fit**: OpenHands and OpenCode, because the repo has a real MCP and API substrate they could consume, but the current OpenHands lane is still `extensions#161` review-pending and the repo does not yet ship a dedicated first-party setup page or branded workflow for them
- **Host-bundle fit**: OpenClaw and ClawHub, because the current repo now ships a dedicated bundle and install/proof notes, while the ClawHub lane is already listed live and still carries the current `suspicious.vt_suspicious` warning instead of a clean approval receipt

Client-specific entry pages:

- [Fileorganize MCP For Codex](./codex_mcp.md)
- [Fileorganize MCP For Claude Code](./claude_code_mcp.md)

## Quick Verification

Use these commands when you want to prove the MCP surface exists before wiring a client:

```bash
~/.cache/fileorganize/venv/default/bin/fileorganize-mcp --help
~/.cache/fileorganize/venv/default/bin/fileorganize-mcp --print-tools
~/.cache/fileorganize/venv/default/bin/fileorganize-mcp --print-resources
```

## Current V1 Tool Families

The exact tool names live in the server and client config, but the current v1 surface is intentionally narrow:

| Tool family | Why it exists | Safety boundary |
| :-- | :-- | :-- |
| `runtime.settings.get` | inspect the current local-first workspace defaults before creating work | read-only |
| `analyze.create` | start a local analyze job for a batch | creates a draft job only; does not apply file changes |
| `jobs.list` / `jobs.get` | inspect local job state | read-only |
| `review_queue.get` | read the current review queue, copilot summary, and collections | read-only |
| `manifest.get` | inspect resolved manifest rows | read-only |
| `manifest.patch_row` / `manifest.batch_patch` | update the overlay through the same review-safe path as the WebUI | writes to overlay only, not disk moves |
| `review_rule.preview` / `review_rule.apply` | preview or apply a rule against the overlay | preview/apply stay inside the review layer |
| `apply.preview` | queue a dry-run apply job | no direct execute shortcut |
| `report.get` | read the report plus review bridge context | read-only |
| `strategy_packs.list` / `watch_sources.list` / `inbox.scan` | inspect setup/intake surfaces for recurring work | discovery and template layers only |
| `inbox.analyze` | mirror the explicit inbox-to-analyze handoff from the app | creates an analyze draft only; still no autonomous execution |

## Current V1 Resources

`Fileorganize MCP v1` currently ships **tools + resources**. It does not claim a broader hosted control plane, and it does not need remote transports or a prompt catalog in v1 to be useful.

`Fileorganize MCP v1` also exposes read-only resources so an agent can load the rules of the road before it starts acting:

| Resource family | Purpose |
| :-- | :-- |
| workflow/safety boundary | explain review-first, overlay-only, dry-run-before-execute, and rollback-ready constraints |
| workflow/tool matrix | map tool families to the parts of the product they touch |
| job-scoped review/report resources | provide read-only access to review queue or report context for one existing job |
| allowlisted docs resource | load the public docs that explain overview, usage, architecture, MCP, and developer guidance |

## Generic Client Wiring

Most MCP-capable clients want a stdio command plus arguments. The exact config format depends on the client, but the important part is simple:

```json
{
  "name": "fileorganize",
  "command": "bash",
  "args": ["/absolute/path/to/fileorganize/tooling/runtime/run_mcp_stdio.sh"]
}
```

If your client supports a working directory field, point it at the repository root. If it prefers installed entrypoints and you have the package-installed console script available, use `fileorganize-mcp` instead.

If you want a client-specific landing page instead of a generic MCP snippet:

- Codex users should start with [Fileorganize MCP For Codex](./codex_mcp.md)
- Claude Code users should start with [Fileorganize MCP For Claude Code](./claude_code_mcp.md)

## Safety Notes For Agent Authors

- Prefer `review_queue.get`, `manifest.get`, `report.get`, and the read-only resources before taking any overlay action.
- Treat `manifest.patch_*` and `review_rule.apply` as **review-layer edits**, not as execution.
- Use `apply.preview` before any human decides whether a real apply should happen.
- `apply.execute` is intentionally absent from Fileorganize MCP v1.
- Do not describe `Fileorganize MCP v1` as a tool that “organizes files automatically.” That would be false and would erase the core product boundary.

## Where To Go Next

- [Developer Guide](./developer_guide.md)
- [Operator Guide](./usage.md)
- [Architecture](./architecture.md)
- [Review-First AI File Organizer](./review_first_ai_file_organizer.md)
