# Runtime Topology Reference

> AUTO-GENERATED from `ops/compose/docker-compose.yml`, `contracts/governance/governance.defaults.env`, `contracts/runtime/filesystem_layout.yaml`, `pyproject.toml`, `package.json`, `.env.example`. Do not edit manually.
> Navigation note: this page is the shared runtime-topology reference for README / docs/usage / docs/architecture, and it is the canonical anchor for executable gates and default entry facts.
> Public docs use semantic placeholders to avoid over-publishing local workspace layouts.
> `<workspace-root>` means a user-chosen persistent workspace directory; `<repo-runtime-cache>` means the repo-local runtime cache directory.

## Compose Services

| service | ports | network_mode | command |
| --- | --- | --- | --- |
| `fileman-ci` | — | `default` | — |
| `fileman-web-api` | `${FILEMAN_WEB_API_PORT:-18080}:18080`, `${FILEMAN_WEBUI_PORT:-5173}:5173` | `default` | `bash tooling/runtime/run_web_api.sh --host 0.0.0.0 --port 18080` |
| `fileman-webui` | — | `service:fileman-web-api` | `bash tooling/runtime/run_webui.sh --host 0.0.0.0 --port 5173` |

## Runtime Paths

| key | value |
| --- | --- |
| `GOVERNANCE_PERSISTENT_ARTIFACTS_DIR` | `<workspace-root>/.fileman/artifacts` |
| `GOVERNANCE_RUNTIME_BUILD_DIR` | `<repo-runtime-cache>/build` |
| `GOVERNANCE_RUNTIME_CACHE_ROOT` | `<repo-runtime-cache>` |
| `GOVERNANCE_RUNTIME_CI_CONTRACT_DIR` | `<repo-runtime-cache>/ci-contract` |
| `GOVERNANCE_RUNTIME_CI_DIR` | `<repo-runtime-cache>/ci` |
| `GOVERNANCE_RUNTIME_CODEGEN_DIR` | `<repo-runtime-cache>/codegen` |
| `GOVERNANCE_RUNTIME_ENV_FILE` | `<workspace-root>/.fileman/env/runtime.env` |
| `GOVERNANCE_RUNTIME_LOG_DIR` | `<repo-runtime-cache>/logs` |
| `GOVERNANCE_RUNTIME_MUTMUT_CACHE_FILE` | `<repo-runtime-cache>/test/mutation/.mutmut-cache` |
| `GOVERNANCE_RUNTIME_TEMP_DIR` | `<repo-runtime-cache>/tmp` |
| `GOVERNANCE_RUNTIME_TEST_DIR` | `<repo-runtime-cache>/test` |
| `GOVERNANCE_RUNTIME_VENV_DIR` | `~/.cache/fileman/venv/default` |
| `GOVERNANCE_WEBUI_LOCK_HASH_FILE` | `<repo-runtime-cache>/build/apps/webui/.fileman_webui_lock_hash` |

## Default Runtime Knobs

| key | default |
| --- | --- |
| `GEMINI_MODEL` | `gemini-3-flash-preview` |

## Cleanup Rails

- **repo-local residue**: `bash tooling/cleanup/prune_repo_runtime.sh`
  Trim checkout-local runtime noise under <repo-runtime-cache>.
- **machine cache**: `bash tooling/cleanup/prune_machine_cache.sh --safe`, `bash tooling/cleanup/prune_machine_cache.sh --rebuildable`, `bash tooling/cleanup/prune_machine_cache.sh --aggressive-host`
  Governed host-side cache lane; host venv is fallback-only in the container-first model.
- **docker runtime**: `bash tooling/cleanup/prune_docker_runtime.sh --dry-run`, `bash tooling/cleanup/prune_docker_runtime.sh --rebuildable`, `bash tooling/cleanup/prune_docker_runtime.sh --aggressive`
  Canonical runtime rail backed by the current Docker image, named volumes, and repo-related build cache.
- **destructive workspace reset**: `bash tooling/runtime/runtime_reset.sh --confirm-workspace-reset`
  Clears workspace .fileman state; not a routine cache cleanup command.

### Container-First Defaults

- Canonical Docker image: `fileman-ci:local`
- Protected Docker volumes: `fileman-web-stack_fileman_playwright`, `fileman-web-stack_fileman_venv`
- Optional Docker volumes: `fileman-web-stack_fileman_webui_node_modules`
- Shared-related surface: `docker build cache`

## Entrypoints

### Python entrypoints

- `fileman` -> `apps.cli.fileman:main`
- `fileman-web-api` -> `apps.api.server:main`
- `fileman-mcp` -> `apps.mcp.server:main`

### Package smoke required entrypoints

- `fileman`
- `fileman-web-api`
- `fileman-mcp`

### Workspace scripts

- `dev:stack` -> `bash tooling/runtime/run_web_stack.sh --mode local`
- `dev:stack:compose` -> `bash tooling/runtime/run_web_stack.sh --mode compose`
- `build` -> `bash tooling/runtime/run_webui_task.sh build`

### WebUI scripts

- `dev` -> `vite`
- `build` -> `tsc -b && vite build`
- `test` -> `vitest run`
- `lint` -> `eslint . --max-warnings=0`
