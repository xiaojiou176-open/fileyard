# Fileman Brand Positioning

This note freezes the current naming baseline for the public docs, README, WebUI, and agent-facing surfaces.

## Core Positioning

- **Primary brand**: `Fileman`
- **Repository and CLI/runtime identity**: `fileman`
- **Current product promise**: review-first, AI-assisted, dry-run before execute, rollback-ready, local-first

Short product sentence:

> **Fileman is a review-first local file organizer and workbench.**
> AI helps draft the plan, but deterministic execution still waits for human review.

## Current Stable Surface Names

These names can appear in README, docs, and WebUI today because they describe real current surfaces:

- **Fileman Review**: the review queue and manifest-approval layer before execution
- **Fileman Rules**: the rule authoring and rule-draft workflow
- **Fileman Inbox**: the scan and intake surface for incoming batches and watch sources
- **Fileman Copilot v1**: the current review-only guidance surface
- **Fileman MCP v1**: the current stdio/local-first extension surface for agents and developers

## Reserved Future Surface Names

These names are still roadmap vocabulary only. They should not be written as shipped features today:

- **Fileman Copilot** beyond the current review-only v1 scope
- **Rule from Examples** beyond the current draft-seeding workflow
- any future remote or hosted form of `Fileman MCP`

Allowed phrasing:

- `current review-only surface`
- `future roadmap language`
- `not part of the current primary product promise`

Disallowed phrasing:

- `available now`
- `included in the current app`
- `Fileman MCP is a hosted automation platform`
- `Fileman already auto-organizes files through agents`

## What Fileman Is

- a **local-first** workflow
- a **review-first** organizer and workbench
- an **AI-assisted** planning surface
- a **deterministic apply/rollback** execution system

## What Fileman Is Not

- not a hosted SaaS
- not a multi-user cloud organizer
- not an AI-autonomous organizer that mutates files without review
- not a generic agent platform whose main story is MCP before the review workflow exists
- not a direct file-mutation server for agents

## Copy Guardrails

- Prefer `AI-assisted` over `AI-powered` when the sentence could imply autonomy.
- Prefer `Apply approved changes` or `dry-run before execute` over marketing verbs that hide the review boundary.
- Keep `Fileman` as the outward-facing brand, but keep `fileman` for repo, CLI, package, and runtime references.
- When in doubt, describe the current product as a **workbench** or **workspace**, not a cloud service.
