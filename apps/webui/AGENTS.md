# AGENTS.md (webui)

Local policy for `apps/webui/`.

## Goal

Maintain the Fileorganize WebUI as a thin control surface for job orchestration, conflict review, and reporting.

## Stack

- React
- TypeScript
- Vite
- Tailwind CSS
- Radix primitives

## Rules

- Keep changes scoped.
- Prefer existing UI primitives and hooks.
- Sync docs when routing, flow, or API usage changes.
- Never hardcode secrets or private endpoints.

## Main checks

```bash
npm run lint
npm run test
npm run build
```
