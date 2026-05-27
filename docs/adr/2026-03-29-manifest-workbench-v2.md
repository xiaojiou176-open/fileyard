# ADR 2026-03-29: Manifest Workbench V2 stays manifest-first, local-first, and review-first

## Status

Accepted

## Context

The repository already had a strong execution spine:

- `analyze` produces the base manifest and recommendation hints
- `overlay` captures operator edits without mutating the base manifest
- `resolved snapshot` is the review and apply view that the system can audit
- `apply` and `rollback` keep filesystem changes bounded and reversible

The missing layer was operator leverage.
The Web API and WebUI were real, but they still pushed too much row-by-row judgment back onto the operator.
That created a maturity illusion: the repo looked like a finished workbench even though the high-value review layer was still thin.

## Decision

Manifest Workbench V2 must evolve on top of the existing execution spine instead of creating a second truth surface.

The accepted constraints are:

1. Keep the execution contract `manifest -> overlay -> resolved snapshot -> apply`.
2. Make the post-analyze default landing surface review-first through `Review Queue`, not direct row-table editing.
3. Model `ReviewRule` as a first-class object and let `Rule Studio` generate overlay patches only.
4. Keep `saved views` and `naming templates` as separate preference objects; they do not silently become the rule system.
5. Store durable workbench state under `<workspace-root>/.fileman/preferences/`, not repo root and not `.runtime-cache/`.
6. Ship `Strategy Packs` from the repo as curated presets instead of opening a plugin marketplace or multi-user control plane.
7. Allow `Watch Inbox` to create analyze jobs and feed the review queue, but never auto-apply filesystem changes.
8. Keep the product local-first; this wave explicitly rejects DB-first, SaaS-first, and multi-user scope expansion.

## Consequences

- New review features must remain contract-first and fail-closed under the existing gate stack.
- Any future automation that changes filesystem results must still flow through overlay and resolved snapshot semantics.
- Durable operator memory is allowed, but it must stay workspace-local, inspectable, and removable.
- Faster operator UX is encouraged, but never at the cost of bypassing dry-run, manifest review, or rollback boundaries.
