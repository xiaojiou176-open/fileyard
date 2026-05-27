# Support

Think of this file like the front desk in a building: it tells you which
door to use first so the right conversation starts in the right place.

## Support Boundary

This repository is a limited-maintenance public project, not a hosted
service.

Reasonable expectations:

- Triage for reproducible bugs
- Corrections for incorrect or stale documentation
- Clarifications for the main workflows: `analyze`, `apply`, `rollback`,
  and `report`

Do not assume:

- Private consulting or custom feature delivery
- Automatic roadmap acceptance
- Enterprise-grade response SLAs
- Long-term maintenance for old releases

## Start With The Right Door

Use this short routing guide before opening an issue:

| If you need help with... | Go here first | Why |
| :-- | :-- | :-- |
| Basic overview or first run | [README.md](README.md) | This is the fastest public entry point |
| Runtime commands and operator flow | [docs/usage.md](docs/usage.md) | This is the detailed operator guide |
| Architecture and boundaries | [docs/architecture.md](docs/architecture.md) | This explains how the system is wired |
| Release or public platform questions | [docs/open_source_runbook.md](docs/open_source_runbook.md) | This covers release and GitHub-facing rules |
| Usage ideas or workflow discussion | [GitHub Discussions](https://github.com/xiaojiou176-open/fileyard/discussions) | This keeps lightweight questions and ideas out of the bug queue |
| Security concerns | [SECURITY.md](SECURITY.md) | Security reports must stay off public issue threads |

## Before Opening An Issue

Please run the basic local checks first:

```bash
bash tooling/runtime/bootstrap_env.sh
bash tooling/gates/pre_push_gate.sh
bash tooling/docs/docs_smoke.sh --install-smoke
```

If you report that the repository is currently red, include fresh results
for these commands when they are relevant:

- `bash tooling/docs/check_docs_scope.sh`
- `bash tooling/docs/docs_smoke.sh --install-smoke`
- `bash tooling/gates/quality_gate.sh`
- `bash tooling/gates/public_readiness_gate.sh repo`

## Where To Ask What

- Security concerns: follow [SECURITY.md](SECURITY.md)
- Usage questions: start with [README.md](README.md) and [docs/usage.md](docs/usage.md)
- Workflow ideas or broader discussion: start in [GitHub Discussions](https://github.com/xiaojiou176-open/fileyard/discussions)
- Release and platform questions: read [docs/open_source_runbook.md](docs/open_source_runbook.md)

## What Makes A Helpful Support Request

The fastest way to get a useful answer is to include:

- What you were trying to do
- The command or page you used
- What you expected
- What actually happened
- Fresh command output, error text, or screenshots when relevant

## What To Avoid

- Posting security details in public threads
- Asking for custom consulting or feature delivery as standard support
- Reporting old historical behavior without saying which commit, branch, or
  version you tested

## If You Still Need To Open Something

- Reproducible bug: open an issue with fresh evidence
- Documentation mistake: open a docs issue or focused docs pull request
- Workflow idea or usage discussion: open a discussion first
- Security problem: follow [SECURITY.md](SECURITY.md), not public issues

This project is maintained carefully, but not as a 24/7 help desk. A clear,
small, evidence-backed report is much more likely to get traction than a
large vague complaint.
