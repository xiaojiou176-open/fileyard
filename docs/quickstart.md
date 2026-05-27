---
title: Fileman Quickstart
description: The shortest safe first-look route for Fileman using offline fixture files and dry-run apply.
---

This page is the shortest safe first-look route.

It uses fixture files that already live in the repository and keeps `apply` in `--dry-run` mode, so you can inspect the workflow without touching your real folders.

## 1. Bootstrap the runtime

```bash
bash tooling/runtime/bootstrap_env.sh
```

## 2. Generate an offline manifest from the built-in fixture set

```bash
mkdir -p .runtime-cache/storefront-demo
FILEMAN_ALLOW_HOST_EXECUTION=1 bash tooling/runtime/run_analyze.sh \
  --offline \
  --config ./contracts/runtime/config.example.toml \
  --input ./tests/fixtures/golden_input \
  --manifest ./.runtime-cache/storefront-demo/manifest.jsonl \
  --report ./.runtime-cache/storefront-demo/report.json
```

## 3. Preview the file moves without changing anything

```bash
FILEMAN_ALLOW_HOST_EXECUTION=1 bash tooling/runtime/run_apply.sh \
  --config ./contracts/runtime/config.example.toml \
  --manifest ./.runtime-cache/storefront-demo/manifest.jsonl \
  --input-root ./tests/fixtures/golden_input \
  --output ./.runtime-cache/storefront-demo/output \
  --dry-run \
  --verify-sha1 \
  --report ./.runtime-cache/storefront-demo/apply-report.json
```

After step 3, inspect:

- `./.runtime-cache/storefront-demo/manifest.jsonl`
- `./.runtime-cache/storefront-demo/report.json`
- `./.runtime-cache/storefront-demo/apply-report.json`

If you need the full operator path, go to [Operator Guide](./usage.md).
