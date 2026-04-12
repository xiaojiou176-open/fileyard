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
| ClawHub listing | Listed live, still suspicious | Movi is listed live on ClawHub, and the current page still shows `Moderation verdict: suspicious` plus `Detected: suspicious.vt_suspicious`. |
| Submission manifest | Published in-repo | [`manifest.yaml`](./manifest.yaml) is the repo-owned summary of current listed-live, review-pending, not-submitted, and not-published surfaces. |

## Current Repo-Owned Ready Surfaces

| Surface | Current status | What we can truthfully claim |
| :-- | :-- | :-- |
| Source install from this repository | Ready | The repository ships Python package metadata and console entrypoints such as `movi-organizer`, `movi-web-api`, and `movi-mcp`. |
| Movi MCP v1 stdio server | Ready | The MCP surface is a local-first stdio integration that can be launched from this repository or an installed environment. |
| Codex / Claude Code setup docs | Ready | The repository ships setup pages for Codex and Claude Code, but those docs describe local wiring, not a separate public distribution channel. |
| Skills / agent bundle shelf | Ready in-repo | The repository ships repo-owned skill bundle examples and install/proof notes, but a separate public skills marketplace listing is not claimed here. |
| OpenClaw / ClawHub bundle | Ready in-repo | The repository ships an OpenClaw-facing bundle and proof note, while the public catalog truth stays anchored to the live ClawHub page and its current warning label. |

## Current Docs-Safe External Lanes

| Surface | Current status | What we can truthfully claim |
| :-- | :-- | :-- |
| ClawHub | listed_live | Movi is listed live on ClawHub; the current live page still shows `Moderation verdict: suspicious` and `Detected: suspicious.vt_suspicious`. |
| OpenHands `extensions#161` | OPEN / REVIEW_REQUIRED / BLOCKED | Movi has been submitted to OpenHands via PR `#161`, but that lane is still blocked in review and is not the same thing as acceptance. |
| Official MCP Registry | not_submitted | No official MCP Registry submission is claimed today. |
| GHCR | not_published | No public GHCR package or container publication is claimed today. |
| Package / Docker later lanes | no verified public receipt today | The repo may contain packaging guidance or operator notes, but this file does not claim a live public package or container receipt. |

## Surfaces We Do Not Currently Claim As Published

| Surface | Current status | Truthful boundary |
| :-- | :-- | :-- |
| PyPI | Not published | This repository does not currently claim an official PyPI release surface. |
| npm package | Not published | The root Node surface is a repo control surface, not a published npm package. |
| Official MCP Registry | not_submitted | `Movi MCP v1` is documented as a local-first stdio surface, not a submitted or published registry listing. |
| Skills registry | Not published | A repo-owned skills bundle exists, but no live registry listing is claimed. |
| Plugin marketplace | Not published | Agent/plugin bundle readiness exists, but no browser or plugin marketplace listing is claimed. |
| Chrome Web Store | Not published | No official Chrome Web Store distribution claim is made here. |
| GHCR | not_published | No public GHCR package or container publication claim is made here. |

## Current Reading Rule

Use the surfaces above in this order:

1. GitHub repository for the public source of truth
2. GitHub Releases for release history
3. GitHub Pages for the current public landing route
4. ClawHub for the live external listing truth, including its current moderation label
5. `manifest.yaml` for the repo-owned listed-live vs pending-lane summary
6. `server.json` for the canonical pure-MCP descriptor
7. `examples/skills/README.md` and `examples/openclaw/README.md` for repo-owned bundle surfaces

If you need to answer a stricter question such as "is the current head verified
as a published release," do not infer that from a tag alone. Use the release
truth and release evidence workflows instead of promotional copy.
