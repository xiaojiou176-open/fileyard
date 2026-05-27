# Fileorganize SEO Landing Map

This file maps high-intent search language to the current docs surface and future landing opportunities.

The goal is simple: attract people who already want a safer file-organization workflow, not people looking for a vague "AI that does everything."

## Current SEO Promise

Current public surfaces should consistently reinforce this sentence:

> **Fileorganize is a review-first local file organizer and workbench with AI-assisted planning, dry-run execution, and rollback-ready recovery.**

## High-Intent Keywords

These are the search intents the current README/docs can honestly serve today:

| Keyword / phrase | Intent | Current surface |
| :-- | :-- | :-- |
| `review first file organizer` | user wants file organization with a human approval step | `README.md`, `docs/index.md` |
| `local file organizer with dry run` | user wants safety before execution | `README.md`, `docs/usage.md` |
| `rollback ready file organizer` | user cares about undo and audit trail | `README.md`, `docs/usage.md` |
| `AI assisted file organizer` | user wants help drafting labels without full autonomy | `README.md`, `docs/index.md` |
| `review first AI organizer` | user wants AI help without giving up approval control | `README.md`, `docs/review_first_ai_file_organizer.md` |
| `local photo organizer with review queue` | user wants photo cleanup without hidden mutation | `docs/photo_organizer.md`, `README.md` |
| `screenshot organizer with dry run` | user wants screenshot cleanup with review-first safety | `docs/screenshot_organizer.md`, `docs/usage.md` |
| `receipt organizer with rollback` | user wants receipt cleanup with auditability and undo | `docs/receipt_organizer.md`, `docs/usage.md` |
| `manifest based file organizer` | user wants a paper trail and inspectable plan | `docs/usage.md`, `docs/architecture.md` |
| `review queue for file organization` | user cares about triage before execution | WebUI copy, `README.md` |
| `local first MCP file organizer` | developer or agent user wants a safe extension surface | `docs/mcp.md`, `docs/developer_guide.md` |
| `local file organizer API` | builder wants a real local integration contract instead of a vague roadmap promise | `docs/developer_guide.md`, `contracts/api/web_api.openapi.yaml` |
| `typed file organizer client` | builder wants generated client/types instead of hand-written request glue | `docs/developer_guide.md`, `contracts/api/generated/webui/client.ts` |
| `Codex MCP file organizer` | user wants a Codex-friendly MCP workflow for local file organization | `docs/codex_mcp.md`, `docs/mcp.md` |
| `Claude Code MCP file organizer` | user wants a Claude Code-friendly MCP workflow for local file organization | `docs/claude_code_mcp.md`, `docs/mcp.md` |
| `review first MCP for Codex` | user wants review-safe MCP instead of agent-driven execute | `docs/codex_mcp.md` |
| `review first MCP for Claude Code` | user wants review-safe MCP instead of agent-driven execute | `docs/claude_code_mcp.md` |

## Terms To Avoid As Primary SEO Language

These terms either over-promise or attract the wrong audience for the current product:

- `autonomous organizer`
- `hands-free organizer`
- `hosted file organizer SaaS`
- `AI agent that cleans your drive automatically`
- `MCP file organizer` as the only or primary headline today

## Current Landing Ownership

| Surface | Job |
| :-- | :-- |
| `README.md` | front-door overview, product promise, fast trust check |
| `docs/index.md` | docs landing page for review-first value and navigation |
| `docs/usage.md` | operator-intent landing page for commands and workflow truth |
| `docs/review_first_ai_file_organizer.md` | high-intent landing page for people comparing Fileorganize against zero-review AI organizers |
| `docs/photo_organizer.md` | use-case landing page for photo-heavy search intent |
| `docs/screenshot_organizer.md` | use-case landing page for screenshot-heavy search intent |
| `docs/receipt_organizer.md` | use-case landing page for receipt-heavy search intent |
| `docs/mcp.md` | developer/agent landing page for safe MCP access |
| `docs/codex_mcp.md` | Codex-specific integration landing page for the current MCP surface |
| `docs/claude_code_mcp.md` | Claude Code-specific integration landing page for the current MCP surface |
| `docs/developer_guide.md` | capability-to-entrypoint map for humans, developers, and agents |
| `docs/brand_positioning.md` | naming and promise baseline |
| `docs/open_source_runbook.md` | public-boundary and release-boundary clarification |

## Future Landing Map

These are valid future landing topics, but they should not be marketed as fully landed pages yet unless the product surface becomes real:

| Future landing | Purpose | Status |
| :-- | :-- | :-- |
| `Fileorganize Review` | explain review queue, triage, and human approval flow | current surface name, future dedicated landing |
| `Fileorganize Rules` | explain reusable rules and rule drafting | current surface name, future dedicated landing |
| `Fileorganize Inbox` | explain intake/watch-source workflow | current surface name, future dedicated landing |
| `Fileorganize Copilot` | explain review-only AI guidance, batch triage, and draft generation | current review-only surface |
| `Fileorganize MCP` | explain deeper agent workflows or future broader integration layers beyond v1 | current v1 exists; broader surface can expand later |

## Practical Copy Rules

- Put `review-first`, `local-first`, `dry-run`, and `rollback-ready` near the top of every front-door surface.
- Use `AI-assisted` when the user benefit is real, but pair it with the review boundary in the same paragraph.
- Treat `Fileorganize MCP v1` as a current extension surface, but not as the main headline that replaces the core review-first story.
- Treat `Codex` and `Claude Code` as current integration hooks only where the MCP surface already proves the claim.
- Keep `OpenHands`, `OpenCode`, and `OpenClaw` out of the main hero unless the repo ships a stronger first-party integration surface.
- Prefer concrete workflow nouns like `review queue`, `manifest`, `dry-run apply`, and `rollback` over generic AI slogans.
