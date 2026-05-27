---
title: Fileorganize Developer And Agent Guide
description: Choose the right Fileorganize surface for operators, developers, and agents without breaking review-first safety.
---

## Developer And Agent Guide

This page is for people who want to extend Fileorganize, wire it into automation, or plug an agent into the current product surface without breaking the safety contract.

## Surface Map

Use the entry surface that matches the job:

| Surface | Best for | Entry point |
| :-- | :-- | :-- |
| CLI | full operator runs and repeatable shell workflows | `bash tooling/runtime/run_analyze.sh`, `run_apply.sh`, `run_rollback.sh` |
| Web API | local app integration, debugging, and explicit route calls | [`contracts/api/web_api.openapi.yaml`](../contracts/api/web_api.openapi.yaml) |
| Generated TypeScript client | builder-facing WebUI or local tool integrations that want typed API calls | [`contracts/api/generated/webui/client.ts`](../contracts/api/generated/webui/client.ts) + [`contracts/api/generated/webui/types.ts`](../contracts/api/generated/webui/types.ts) |
| WebUI | human review, triage, and job orchestration | `npm run dev:stack` |
| Fileorganize MCP v1 | stdio/local-first agent integrations | `bash tooling/runtime/run_mcp_stdio.sh` (default) or `fileorganize-mcp` when the installed console entrypoint is available |

Think of it like choosing the right door into the same building. The CLI is the loading dock, the WebUI is the front desk, the Web API is the service corridor, and Fileorganize MCP is the guarded service window for agents.

## Quick Picks

If you already know the client you care about, start here:

Use this Navigation table as a search-before-write shortcut: it tells you which builder surface is the right first stop before you wire code against the wrong lane.

| I want to build or use... | Start here | Why this is the shortest honest route |
| :-- | :-- | :-- |
| a Codex workflow | [Fileorganize MCP For Codex](./codex_mcp.md) | it gives the client-specific MCP install path without pretending Codex can bypass review |
| a Claude Code workflow | [Fileorganize MCP For Claude Code](./claude_code_mcp.md) | same local-first MCP lane, but written in Claude Code terms |
| a generic MCP-capable agent | [Fileorganize MCP v1](./mcp.md) | this is the current stdio-first extension contract |
| a local app or script using HTTP | [`contracts/api/web_api.openapi.yaml`](../contracts/api/web_api.openapi.yaml) | the Web API contract is still the public machine-readable truth source |
| a typed TypeScript integration | [`contracts/api/generated/webui/client.ts`](../contracts/api/generated/webui/client.ts) | this is the fastest path when you want typed request helpers instead of hand-writing fetch calls |
| the whole operator flow before integrating | [Operator Guide](./usage.md) | it shows the review-first workflow end-to-end before you wire a client into it |

## Current Contract And Client Substrate

Fileorganize is not just a page app anymore. The current extension stack already has a thin substrate shape:

- **HTTP contract**: [`contracts/api/web_api.openapi.yaml`](../contracts/api/web_api.openapi.yaml) is the public machine-readable contract for the local Web API.
- **Generated client layer**: [`contracts/api/generated/webui/client.ts`](../contracts/api/generated/webui/client.ts) and [`contracts/api/generated/webui/types.ts`](../contracts/api/generated/webui/types.ts) keep the WebUI aligned with the current API shape.
- **MCP facade**: `Fileorganize MCP v1` reuses the same review-safe workflow rather than inventing a second business-logic path.

In plain language: the API contract is the signed blueprint, the generated client is the shared wiring harness, and the MCP layer is another supervised door into the same building.

What this means today:

- the current substrate is **WebUI + Web API + generated client/types + MCP v1**
- a thin TypeScript SDK can grow later from the same contract surface
- a broader SDK story should follow the real contract, not lead the marketing copy

One important boundary to keep straight:

- **presentation copy can be English-first**
- **runtime canonical taxonomy can still stay localized where compatibility policy requires it**

That means WebUI locale work should happen in the display layer and shared copy layer, not by silently rewriting manifest/category compatibility values that the runtime still treats as canonical.

## The Core Safety Boundary

Everything still revolves around the same chain:

1. `analyze` drafts a manifest
2. review surfaces inspect or edit the overlay
3. Fileorganize resolves a snapshot from `base manifest + overlay`
4. `apply` starts with a dry run before real execution
5. `rollback` stays bounded and auditable

That means:

- no direct file-move shortcut for agents
- no hidden second truth source
- no AI path that skips review and jumps straight to execution

## When To Use Fileorganize MCP v1

Use `Fileorganize MCP v1` when you want an agent to:

- inspect current runtime defaults before it creates work
- inspect jobs, review queues, manifests, or reports
- draft or apply overlay-safe review changes
- list strategy packs, watch sources, or inbox batches
- explicitly hand one inbox watch source into Analyze without turning discovery into autonomy
- queue dry-run-safe follow-up work without reaching past review

Use the Web API directly when you are:

- debugging route behavior
- writing local integration tests
- validating request/response shapes against the OpenAPI contract

## Honest Hotness Binding Matrix

This is the shortest accurate ecosystem map for the current repo:

| Ecosystem | Current fit | Why |
| :-- | :-- | :-- |
| Codex | primary | current stdio-first MCP surface already fits local agent workflows |
| Claude Code | primary | current stdio-first MCP surface already fits local agent workflows |
| Cursor / generic MCP clients | secondary | real MCP surface exists, but the repo does not need to brand them as the headline |
| OpenHands | comparison / ecosystem only | real API + MCP substrate exists, but no dedicated first-party setup page or product flow is shipped |
| OpenCode | comparison / ecosystem only | same honest boundary as OpenHands |
| OpenClaw | submission-ready-unlisted | current repo ships a dedicated bundle and install/proof note, but still does not claim a live listing |

If you want the client-specific landing page first:

- [Fileorganize MCP For Codex](./codex_mcp.md)
- [Fileorganize MCP For Claude Code](./claude_code_mcp.md)

## Current Agent-Safe Moves

These actions fit the current product promise:

- get current job, review queue, report, or manifest state
- patch overlay rows
- preview reusable rules
- apply rules to the overlay
- queue dry-run apply jobs

These actions do **not** fit the current product promise:

- direct rename/move without review
- conflict auto-resolution followed by execute
- agent-controlled rollback policy changes
- hosted agent orchestration claims

## Docs To Keep Nearby

- [Fileorganize MCP v1](./mcp.md)
- [Fileorganize MCP For Codex](./codex_mcp.md)
- [Fileorganize MCP For Claude Code](./claude_code_mcp.md)
- [Operator Guide](./usage.md)
- [Architecture](./architecture.md)
- [Brand Positioning](./brand_positioning.md)
- [SEO Landing Map](./seo_landing_map.md)
- [Open Source Runbook](./open_source_runbook.md)

## If You Extend The Product Later

Keep this order:

1. add or adjust the underlying safe workflow first
2. expose it through Web API or application services
3. only then expose it through `Fileorganize MCP`
4. update docs and discoverability copy to match the real shipped boundary

That order matters because the docs are the road signs, not the road. If the road does not exist yet, the sign should not pretend it does.
