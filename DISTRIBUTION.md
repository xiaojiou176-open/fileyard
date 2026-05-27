# Distribution

This file answers one narrow question:

What public distribution surfaces does Fileorganize actually have today?

Think of it like a shipping manifest. It tells you which boxes are really on
the truck, which ones are ready at the warehouse, and which ones have not been
shipped yet.

## Current Published Surfaces

| Surface | Current status | What we can truthfully claim |
| :-- | :-- | :-- |
| GitHub repository | Published | The canonical public source and collaboration surface is `xiaojiou176-open/fileorganize`. |
| GitHub Releases | Published | GitHub Releases is the canonical release trail for this repository. |
| GitHub Pages | Published | GitHub Pages is the current public front door and discovery page. |
| ClawHub listing | Listed live, still suspicious | Fileorganize is listed live on ClawHub, and the current page still shows `Moderation verdict: suspicious` plus `Detected: suspicious.vt_suspicious`. |
| Submission manifest | Published in-repo | [`manifest.yaml`](./manifest.yaml) is the repo-owned summary of current listed-live, review-pending, not-submitted, and not-published surfaces. |

## Current Repo-Owned Ready Surfaces

| Surface | Current status | What we can truthfully claim |
| :-- | :-- | :-- |
| Source install from this repository | Ready | The repository ships Python package metadata and console entrypoints such as `fileorganize`, `fileorganize-web-api`, and `fileorganize-mcp`. |
| Fileorganize MCP v1 stdio server | Ready | The MCP surface is a local-first stdio integration that can be launched from this repository or an installed environment. |
| Pure-MCP registry descriptor | Submission-ready-unlisted | Root [`server.json`](./server.json) names the canonical MCP surface without claiming a live registry publication. |
| Codex / Claude Code setup docs | Ready | The repository ships setup pages for Codex and Claude Code, but those docs describe local wiring, not a separate public distribution channel. |
| Skills / agent bundle shelf | Ready in-repo | The repository ships repo-owned skill bundle examples and install/proof notes, but a separate public skills marketplace listing is not claimed here. |
| OpenClaw / ClawHub bundle | Ready in-repo | The repository ships an OpenClaw-facing bundle and proof note, while the public catalog truth stays anchored to the live ClawHub page and its current warning label. |

## Current Docs-Safe External Lanes

| Surface | Current status | What we can truthfully claim |
| :-- | :-- | :-- |
| ClawHub | listed_live | Fileorganize is listed live on ClawHub; the current live page still shows `Moderation verdict: suspicious` and `Detected: suspicious.vt_suspicious`. |
| OpenHands `extensions#161` | OPEN / REVIEW_REQUIRED / BLOCKED | Fileorganize has been submitted to OpenHands via PR `#161`, but that lane is still blocked in review and is not the same thing as acceptance. |
| Official MCP Registry | not_submitted | No official MCP Registry submission is claimed today. |
| GHCR | not_published | No public GHCR package or container publication is claimed today. |
| Package / Docker later lanes | no verified public receipt today | The repo may contain packaging guidance or operator notes, but this file does not claim a live public package or container receipt. |

## Surfaces We Do Not Currently Claim As Published

| Surface | Current status | Truthful boundary |
| :-- | :-- | :-- |
| PyPI | Not published | This repository does not currently claim an official PyPI release surface. |
| npm package | Not published | The root Node surface is a repo control surface, not a published npm package. |
| Official MCP Registry | not_submitted | `Fileorganize MCP v1` is documented as a local-first stdio surface, not a submitted or published registry listing. |
| Skills registry | Not published | A repo-owned skills bundle exists, but no live registry listing is claimed. |
| Goose Skills Marketplace | review pending, not accepted | PR `#25` exists, but no accepted marketplace listing is claimed until upstream review clears. |
| agent-skill.co source repo | submission done, not accepted | PR `#181` exists, but no accepted public directory entry is claimed while upstream preview authorization still blocks. |
| awesome-opencode | Not submitted | No project/resource entry is claimed because the current product shape is not an honest Opencode-centered fit. |
| Plugin marketplace | Not published | Agent/plugin bundle readiness exists, but no browser or plugin marketplace listing is claimed. |
| Chrome Web Store | Not published | No official Chrome Web Store distribution claim is made here. |
| GHCR | not_published | No public GHCR package or container publication claim is made here. |

## Current Reading Rule

Use the surfaces above in this order:

1. GitHub repository for the public source of truth
2. GitHub Releases for release history
3. GitHub Pages for the current public landing route
4. `manifest.yaml` for the repo-owned submission summary
5. `server.json` for the canonical pure-MCP descriptor
6. `examples/skills/README.md` and `examples/openclaw/README.md` for unlisted bundle surfaces

If you need to answer a stricter question such as "is the current head verified
as a published release," do not infer that from a tag alone. Use the release
truth and release evidence workflows instead of promotional copy.
