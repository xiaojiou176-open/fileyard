# Golden Runner / Capability Contract

This document explains the current CI execution contract for the public repository.
Do not treat this page as a live branch-protection dashboard.
This document explains why the runner contract exists.

This repository is now **Hosted-First**:

- ordinary CI runs on GitHub-hosted runners
- untrusted fork PRs are limited to public, low-cost, no-secret checks
- sensitive live checks are manual-only and must pass through a protected environment

## 1. Scope

- Covered workflows:
  - `.github/workflows/ci.yml`
  - `.github/workflows/pre-commit.yml`
  - `.github/workflows/live-integration.yml`
  - `.github/workflows/mutation-manual.yml`

## 2. Public Collaboration Safety Rules

1. Fork PRs must never depend on repository-owned runners or private capacity.
2. Fork PRs must never require protected secrets to get a basic review signal.
3. Live / external / sensitive checks belong to manual-only paths guarded by a protected environment.
4. Current docs, policy, workflow helpers, and validator logic must describe the same hosted-first model.

## 3. Hosted Execution Model

Think of the CI layout like a public building:

- the **front lobby** is the hosted public PR path
- the **staff workroom** is same-repo heavy verification
- the **locked room** is manual sensitive verification behind approval

The repository should only invite outside contributors into the lobby. They should never be forced through private hallways just to open a pull request.
GitHub org runner inventory no longer depends on fixed machine names.

<!-- BEGIN GENERATED: runner-contract-governance-truth -->
> Auto-generated: hosted CI mode, protected environments, and failure-domain facts live in [generated governance reference](reference/governance_truth.generated.md), and [required checks matrix](required_checks_matrix.md).

- **Bootstrap workflow/job**: `.github/workflows/ci.yml -> ci-bootstrap`
- **Runner model**: `github-hosted-only`
- **Manual-only workflows**: None
- **Protected sensitive environments**: `owner-approved-sensitive`
- **Failure-domain policy count**: dual-lane `13` / legacy-shared-pool-only `0`
<!-- END GENERATED: runner-contract-governance-truth -->

## 4. How This Connects To Repository Gates

- `ci.yml` is the public PR and same-repo verification workflow
- `live-integration.yml` is the manual sensitive workflow
- `check_ci_workflow_hardening.py` and `check_ci_governance_regressions.py` must reject drift back toward shared-pool current truth
- `README.md`, `docs/usage.md`, and `docs/open_source_runbook.md` should describe the hosted-first public contract rather than a private runner topology

## 5. Runtime / Cleanup Boundary

Hosted-first does **not** mean “never clean anything.” It means cleanup should happen through repo-owned, documented rails:

- repo runtime residue: `bash tooling/cleanup/prune_repo_runtime.sh`
- machine cache cleanup: `bash tooling/cleanup/prune_machine_cache.sh --safe`
- docker runtime cleanup: `bash tooling/cleanup/prune_docker_runtime.sh --dry-run`

Historical shared-runner cleanup tooling may still exist for forensic or migration reasons, but it is **not** part of the current public collaboration model.

## 6. Current Truth Routes

The live source of truth is:
The only live source of truth is:

- `contracts/governance/required_checks_policy.yaml`
- `docs/required_checks_matrix.md`
- `docs/reference/governance_truth.generated.md`

This page keeps the **why** behind the hosted-first contract.
The question of “which checks are required today” should be answered by the generated projections above, not by stale prose.
