# Environment Contract Policy

This file explains the policy layer of environment configuration.

The machine-readable source of truth is:

- `contracts/runtime/env_contract_registry.yaml`

The rendered reference is:

- `docs/reference/env_contract.generated.md`

The template entrypoint is:

- `.env.example`

## Runtime Sources and Priority

- Allowed runtime sources:
  - `<workspace-root>/.fileman/env/runtime.env`
  - current process environment variables
- Priority:
  - current process environment
  - workspace runtime env file

The repository root `.env` file is local-only, must remain untracked, and is not a supported runtime source.

Use the workspace runtime env file when you need a durable runtime source:

- `<workspace-root>/.fileman/env/runtime.env`

Treat the repository root `.env` file as a local operator convenience only. It must not become the canonical runtime truth, and repository docs or UI copy must not describe it as the supported runtime source.

## Policy Notes

- Sensitive values such as `GEMINI_API_KEY` and `FILEMAN_ROLLBACK_HMAC_KEY` must never be committed.
- `.env.example` stays minimal and public-safe.
- Contract enforcement is checked by the gate stack and docs rendering checks.
- Do not modify the baseline outside a governance cycle.
- The `--broad-total` override is governance-cycle-only and must carry an explicit governance ticket.
