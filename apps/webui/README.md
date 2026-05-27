# Fileman WebUI

Web front-end for Fileman, built with React + TypeScript + Vite.

## Product Flow

- `/setup` handles first-run onboarding: API Key, default source folder, default organized-output folder, and Analyze defaults.
- `/review/:jobId` is now the default review-first landing surface after Analyze. It summarizes triage buckets, inferred collections, learned suggestions, and Rule Studio actions before you drop into row-level editing.
- `/analyze` handles the current batch: use the connected folder or temporarily upload a folder/files, then run Analyze.
- `/manifest`, `/conflicts`, `/apply`, `/report`, `/rollback`, and `/inbox` stay focused on row editing, conflict handling, execution, recovery, and intake automation instead of storing long-term credentials.

## UI Standardization Baseline

This app uses a shadcn/new-york style system and keeps page-level actions aligned to shared primitives.

- Source of truth: `apps/webui/components.json`
- Style profile: `new-york`
- CSS variables: enabled (`tailwind.cssVariables = true`)
- Animation chain: `tailwindcss-animate` + `data-[state]` classes
- Primitive layer: `apps/webui/src/components/ui/*` (Radix + CVA wrappers)

## Component Rules

- Use shared `Button` from `@/components/ui/button` for page/action triggers.
- Avoid adding raw `<button>` in pages or feature components. Keep raw `<button>` only inside `src/components/ui/*` primitives.
- Keep button semantics explicit: route navigation should use `Button asChild` + `Link`, action triggers use `Button`, and form submission actions should set `type="submit"` explicitly when needed.
- Keep modal/sheet/dropdown/select/tabs interactions on Radix-backed primitives from `apps/webui/src/components/ui/*`.
- Keep motion classes consistent with Tailwind plugin support (`animate-in`, `animate-out`, `slide-*`, `fade-*`, `zoom-*`).
- Lint guard: `apps/webui/eslint.config.js` blocks raw `<button>` in `src/**/*.{tsx,jsx}` except `src/components/ui/**` and `src/test/**`.

## Dev Commands

From `apps/webui/`:

```bash
npm run lint
npm run test
npm run build
```

- Dependency note: `apps/webui/package.json` uses `overrides` to pin audited transitive fixes for `flatted` and `undici`; keep `package-lock.json` in sync when refreshing dependencies.

Optional quick check for accidental raw buttons:

```bash
rg -n "<button" apps/webui/src
```

## API Contract (Generated Backend Truth Snapshot)

WebUI consumes the backend routes defined in `apps/api/web_api.py` and wrapped by `apps/webui/src/lib/api.ts`.

<!-- BEGIN GENERATED: webui-api-contract -->
> Auto-generated: current Web API facts come from `contracts/api/web_api.openapi.yaml`; the full method/path list lives in [generated reference](../docs/reference/web_api_routes.generated.md).

- **Jobs / history**: `/api/jobs`, `/api/jobs/history`, `/api/jobs/stream`, `/api/jobs/{job_id}`, `/api/jobs/{job_id}/review-queue`, `/api/jobs/{job_id}/review-queue/batch-triage`, `/api/jobs/{job_id}/review-rules/apply`, `/api/jobs/{job_id}/review-rules/from-examples`, `/api/jobs/{job_id}/review-rules/preview`
- **Job events**: `/api/jobs/{job_id}/events`, `/api/jobs/{job_id}/events/stream`, `/api/jobs/{job_id}/stream`
- **Manifest operations**: `/api/jobs/{job_id}/manifest`, `/api/jobs/{job_id}/manifest/batch`, `/api/jobs/{job_id}/manifest/conflicts`, `/api/jobs/{job_id}/manifest/conflicts/resolve`, `/api/jobs/{job_id}/manifest/rows/{row_id}`, `/api/jobs/{job_id}/manifest/view`, `/api/jobs/{job_id}/manifest/{row_id}/preview`
- **Job actions**: `/api/jobs/analyze`, `/api/jobs/apply`, `/api/jobs/rollback`, `/api/jobs/{job_id}/cancel`, `/api/jobs/{job_id}/retry`
- **Report / audit**: `/api/jobs/{job_id}/audit`, `/api/jobs/{job_id}/report`
- **Preferences**: `/api/preferences/learned-rules`, `/api/preferences/naming-templates`, `/api/preferences/review-rules`, `/api/preferences/runtime`, `/api/preferences/runtime/validate`, `/api/preferences/strategy-packs`, `/api/preferences/views`, `/api/preferences/watch-sources`
- `overlay` / `resolved snapshot` are internal model and file-output concepts, not stable public HTTP routes.
<!-- END GENERATED: webui-api-contract -->
