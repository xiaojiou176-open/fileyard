# Integrations

This file answers a different question from `DISTRIBUTION.md`:

What integration surfaces does Movi actually fit today?

Think of it like a map of doors into the same workshop. Some doors are first
class, some are side entrances, and some are only comparison points.

## Core Integration Surfaces

| Surface | Current role | Truthful boundary |
| :-- | :-- | :-- |
| CLI | Primary operator surface | Best for full analyze, apply, rollback, and report workflows. |
| Web API | Local integration substrate | A local HTTP contract exists for app and builder integration. |
| Generated TypeScript client | Builder substrate | The repository exposes generated client/types for local integrations. |
| Movi MCP v1 | Primary agent integration surface | The canonical agent-facing surface is local-first stdio MCP. |

## Primary Fit

| Client | Why it is a primary fit | Boundary |
| :-- | :-- | :-- |
| Codex | The repository already ships a dedicated Codex MCP setup page and local-first stdio wiring. | This is local MCP wiring, not a hosted service. |
| Claude Code | The repository already ships a dedicated Claude Code MCP setup page and local-first stdio wiring. | This is local MCP wiring, not a hosted service. |

## Secondary Fit

| Client family | Why it is a secondary fit | Boundary |
| :-- | :-- | :-- |
| Cursor and other local MCP-capable clients | The current transport and tool surface already match their local MCP model. | The repository does not currently promote them as the front-door story. |

## Comparison-Only Fit

| Client family | Why it stays comparison-only | Boundary |
| :-- | :-- | :-- |
| OpenHands | A real API and MCP substrate exists, but no dedicated first-party setup page or branded workflow is shipped. | Do not present it as a primary or secondary front-door integration. |
| OpenCode | Same honest boundary as OpenHands. | Do not present it as a primary or secondary front-door integration. |

## Not A Front-Door Fit Today

| Surface | Why it is not front-door fit today |
| :-- | :-- |
| OpenClaw | The repository does not currently ship a dedicated integration surface or branded product flow for it. |
| MCP registry listings | The current story is local-first stdio MCP, not registry publication. |
| Skills registry or plugin marketplaces | The repository does not currently claim those as shipped integration channels. |

## Safety Boundary

All current integrations share the same safety line:

- review-first
- overlay-only editing for review state
- dry-run before execute
- no hidden `apply.execute` shortcut in `Movi MCP v1`

If a description crosses that line, it is overstating the current integration
surface.
