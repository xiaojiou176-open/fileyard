---
title: Fileman FAQ
description: Common questions about Fileman, offline mode, local-first workflow, and support routes.
---

## Does Fileman call Gemini every time

No. `analyze` may call Gemini when you are not in offline mode. `apply` and `rollback` do not call Gemini.

## Can I try it without risking my real folders

Yes. The public quickstart uses the fixture files under `tests/fixtures/golden_input` and keeps `apply` in `--dry-run` mode.

## Is Fileman a hosted product

No. Fileman is a limited-maintenance open-source repository with a local-first workflow.

## Where should I ask questions

- Usage or workflow questions: [GitHub Discussions](https://github.com/xiaojiou176-open/fileman/discussions)
- Bug reports with fresh evidence: GitHub Issues
- Security problems: [SECURITY.md](../SECURITY.md)

## Where do I find the deeper operational truth

- Full operator route: [usage.md](./usage.md)
- Architecture: [architecture.md](./architecture.md)
- Release and platform boundary: [open_source_runbook.md](./open_source_runbook.md)
