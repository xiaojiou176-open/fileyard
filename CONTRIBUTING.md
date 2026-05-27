# Contributing

Thank you for helping improve Movi.

Think of this file like the sign next to a workshop door: it tells you
what kind of help is useful, what to check before walking in, and what is
unlikely to be accepted.

## Start Here

If you are new, use this quick route:

1. Read the public overview in [README.md](README.md).
2. If your question is about usage or setup, read [SUPPORT.md](SUPPORT.md)
   before opening a pull request.
3. If you still want to contribute code or docs, start with a small,
   reproducible change.
4. If your idea is larger than a bug fix or docs change, start in
   [GitHub Discussions](https://github.com/xiaojiou176-open/fileyard/discussions)
   before building a large diff.

## Good First Contributions

These are the safest ways to help:

- Reproducible bug fixes with a clear before/after explanation
- Documentation fixes, examples, spelling fixes, and navigation repairs
- Small maintainability improvements that do not change public contracts
- Test additions that follow the current governance and quality rules

## Changes That Usually Need Prior Alignment

These are not forbidden, but they often need discussion before you invest
time:

- Large product-direction rewrites
- Major UI or interaction redesigns
- Large new provider or external integration work
- Proposals that break the design rule of using AI in `analyze` while
  keeping `apply` and `rollback` deterministic

## Before You Open A Pull Request

Run the standard local checks:

```bash
bash tooling/runtime/bootstrap_env.sh
bash tooling/gates/pre_push_gate.sh
bash tooling/docs/docs_smoke.sh --install-smoke
```

If your change touches runtime behavior, repository layout, public docs,
or CI / release surfaces, also run:

```bash
bash tooling/gates/quality_gate.sh
bash tooling/gates/public_readiness_gate.sh repo
```

## Pull Request Expectations

Please include:

- What changed
- Why it changed
- How you verified it
- Any risk, migration note, or boundary you intentionally did not cross

Keep the diff honest and reviewable:

- Do not submit real secrets, `.env` files, personal machine paths, or
  temporary artifacts
- Keep repo-local tool state untracked. Roots such as `.serena/`,
  `.agents/`, `.runtime-cache/`, and `.env` are local-only surfaces, not
  product files
- Do not add compatibility shims just to hide the real problem
- Keep documentation, contracts, templates, and gate entrypoints aligned

## Current Truth Surface

This repository no longer uses a repo-local `.agents/Tasks` TaskBoard as an
active source of truth.

Use the versioned repository surfaces on `main` instead:

- `README.md` and `docs/` for public product and operator guidance
- `DISTRIBUTION.md` and `INTEGRATIONS.md` for root-level public boundary truth
- contracts, workflows, and generated references for executable truth
- current repository settings and branch protection for GitHub-side policy

Repo-local `.agents/Conversations` or other scratch coordination notes may still
exist during a session, but they are local-only operator residue rather than a
committed planning contract.

Treat `.agents/` as local operator state, not as a committed planning system
that needs a mirrored TaskBoard update on `main`.
If `.agents/Tasks` is absent in a clean checkout, treat that as expected
repository state rather than as governance drift.

## Closed Dependabot Pull Requests

Closed-but-unmerged Dependabot pull requests in this repository are kept as
audit history of automated dependency-update attempts that were later closed
without merge.

Use the following rule when describing them:

- only call a PR a grouped update when `.github/dependabot.yml` directly
  supports that grouping
- only call a PR later superseded when current `main` clearly carries the same
  or a newer dependency state
- if current `main` still pins an older version, describe the PR as closed
  audit history without claiming the proposal landed
- do not treat a closed PR by itself as proof that the proposed dependency
  state landed
- maintainer comments on individual closed PRs should follow the same rule and
  should say when a closure is only grouped audit history, duplicate audit
  history, or non-landed audit history

## Atomic Commit Guidance

Think of the atomic-commit gate like an airline carry-on sizer: it is there
to keep every push small enough to inspect safely, not to punish useful
work.

Use this forward-safe route:

- Batch new work into small, reviewable commits before you push
- If pre-push reports older oversized commits in your local push range, do
  not widen allowlists or weaken the gate
- Instead, branch from an up-to-date `main` and replay only the intended
  changes as smaller commits

This keeps future pushes clean without trying to hide or rewrite repository
history through governance exceptions.

## If You Are Unsure Where To Start

- Usage question: go to [SUPPORT.md](SUPPORT.md)
- Security issue: go to [SECURITY.md](SECURITY.md)
- Workflow idea or broad discussion: start in
  [GitHub Discussions](https://github.com/xiaojiou176-open/fileyard/discussions)
- Small docs or typo fix: open a focused pull request
- Bigger feature idea: describe the problem first before building a large diff

## Maintenance Posture

This is a limited-maintenance public repository.

That means:

- Pull requests are reviewed seriously
- Merge timing is not guaranteed
- Not every roadmap idea will be accepted

Please treat contribution like helping a careful small workshop, not like
filing work into a high-throughput platform team.
