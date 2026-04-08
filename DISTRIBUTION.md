# Distribution

This file answers one narrow question:

What public distribution surfaces does Movi actually have today?

Think of it like a shipping manifest. It tells you which boxes are really on
the truck, which ones are ready at the warehouse, and which ones have not been
shipped yet.

## Current Published Surfaces

| Surface | Current status | What we can truthfully claim |
| :-- | :-- | :-- |
| GitHub repository | Published | The canonical public source and collaboration surface is `xiaojiou176-open/movi-organizer`. |
| GitHub Releases | Published | GitHub Releases is the canonical release trail for this repository. |
| GitHub Pages | Published | GitHub Pages is the current public front door and discovery page. |

## Current Ready But Not Registry-Published

| Surface | Current status | What we can truthfully claim |
| :-- | :-- | :-- |
| Source install from this repository | Ready | The repository ships Python package metadata and console entrypoints such as `movi-organizer`, `movi-web-api`, and `movi-mcp`. |
| Movi MCP v1 stdio server | Ready | The MCP surface is a local-first stdio integration that can be launched from this repository or an installed environment. |
| Codex / Claude Code setup docs | Ready | The repository ships setup pages for Codex and Claude Code, but those docs describe local wiring, not a separate public distribution channel. |

## Surfaces We Do Not Currently Claim As Published

| Surface | Current status | Truthful boundary |
| :-- | :-- | :-- |
| PyPI | Not published | This repository does not currently claim an official PyPI release surface. |
| npm package | Not published | The root Node surface is a repo control surface, not a published npm package. |
| MCP registry | Not published | `Movi MCP v1` is documented as a local-first stdio surface, not a registry-published listing. |
| Skills registry | Not published | No official skills-registry distribution claim is made here. |
| Plugin marketplace | Not published | Strategy Packs are templates, not a plugin marketplace. |
| Chrome Web Store | Not published | No official Chrome Web Store distribution claim is made here. |

## Current Reading Rule

Use the surfaces above in this order:

1. GitHub repository for the public source of truth
2. GitHub Releases for release history
3. GitHub Pages for the current public landing route

If you need to answer a stricter question such as "is the current head verified
as a published release," do not infer that from a tag alone. Use the release
truth and release evidence workflows instead of promotional copy.
