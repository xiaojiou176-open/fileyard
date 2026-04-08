# Governance Truth Reference

> AUTO-GENERATED from `contracts/governance/done_signal_policy.yaml`, `contracts/governance/public_readiness_policy.yaml`, `contracts/governance/required_checks_policy.yaml`, and GitHub workflow topology. Do not edit manually.
> Navigation note: this page carries the high-drift done-signal, required-checks, runner-capacity, and platform-alignment facts; longer human docs should keep only why/rule/tradeoff/runbook explanations.

## Done Signal Truth

- **Delivery-complete gate**: `bash tooling/gates/quality_gate.sh`
- **Repo governance scorecard**: `bash tooling/gates/verify_repo_final.sh`
- **Claim surfaces guarded by policy**: `4`

## Required Checks Snapshot

- **Workflow files**: `.github/workflows/ci.yml`, `.github/workflows/trivy-fs.yml`, `.github/workflows/trufflehog.yml`, `.github/workflows/zizmor.yml`
- **Branch protection target**: `main`
- **Required checks count**: `16`
- **Dual hosted-lane required jobs**: `fork-pr-safety-gate`, `commit-message-lint`, `atomic-commit-gate`, `secrets-supply-chain-gate`, `lint-backend`, `lint-frontend`, `webui-build-test`, `ci-hardening-gate`, `quality-gate-full`, `packaging-gate`, `mutation-canary-gate`, `functional-gate`, `test`
- **Legacy shared-pool-only required jobs**: None

## Hosted CI Contract

- **Bootstrap workflow/job**: `.github/workflows/ci.yml -> ci-bootstrap`
- **Runner model**: `github-hosted-only`
- **Manual-only workflows**: None
- **Protected sensitive environments**: `owner-approved-sensitive`

## Public Readiness / Platform Alignment

- **Repo public readiness gate**: `bash tooling/gates/public_readiness_gate.sh repo`
- **Release public readiness gate**: `bash tooling/gates/public_readiness_gate.sh release`
- **Platform alignment gate**: `bash tooling/gates/platform_alignment_gate.sh`
- **Required repo surface files**: `28`
- **Required package scripts**: `5`
- **Release-mode requires tracked public files**: `yes`
- **Release-mode requires public repo**: `yes`
- **Release-mode requires PVR**: `yes`
- **Release-mode requires branch protection**: `yes`
