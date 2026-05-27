#!/usr/bin/env python3
"""Validate strict hardening invariants for .github/workflows/ci.yml."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PINNED_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
REMOTE_ACTION_USES = re.compile(r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)(?:/(?P<path>[^@]+))?@(?P<ref>.+)$")
REMOTE_ACTION_USES_NO_REF = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^@]+)?$")
DOCKER_IMAGE_USES = re.compile(r"^docker://[^@]+@sha256:[0-9a-fA-F]{64}$")
SELF_HOSTED_SHARED_POOL = {"self-hosted", "shared-pool"}
GITHUB_HOSTED_PRIMARY = "ubuntu-latest"
HYGIENE_SCRIPT_SNIPPET = "bash tooling/ci/gha_self_hosted_hygiene.sh"
WORKSPACE_CACHE_PATTERN = re.compile(r"^(?:\./)?(?:\.venv|\.cache|\.pytest_cache|\.mypy_cache|\.ruff_cache)(?:/.*)?$")
WORKSPACE_ENV_KEYS = {"PRE_COMMIT_HOME", "XDG_CACHE_HOME", "PIP_CACHE_DIR", "FILEMAN_VENV_DIR"}
WORKSPACE_CACHE_PATTERNS = (
    ".venv",
    "./.venv",
    ".cache",
    "./.cache",
    ".pytest_cache",
    "./.pytest_cache",
    ".mypy_cache",
    "./.mypy_cache",
    ".ruff_cache",
    "./.ruff_cache",
)
SELF_HOSTED_HYGIENE_SCRIPT = "tooling/ci/gha_self_hosted_hygiene.sh"
HYGIENE_SCRIPT_TOKEN = "tooling/ci/gha_self_hosted_hygiene.sh"
RUNNER_TEMP_TOKENS: tuple[str, ...] = (
    "${{ runner.temp }}",
    "${{ runner.tool_cache }}",
    "${{ env.RUNNER_TEMP }}",
    "${{ env.RUNNER_TOOL_CACHE }}",
    "$RUNNER_TEMP",
    "${RUNNER_TEMP}",
    "$RUNNER_TOOL_CACHE",
    "${RUNNER_TOOL_CACHE}",
    "$RUNNER_TOOL_CACHE",
    "/tmp/",
    "/var/tmp/",
)
WORKSPACE_TOKENS = (
    "${{ github.workspace }}",
    "${{ env.GITHUB_WORKSPACE }}",
    "$GITHUB_WORKSPACE",
    "${GITHUB_WORKSPACE}",
)
HOME_TOKENS = (
    "~/.cache",
    "~/",
    "$HOME/.cache",
    "${HOME}/.cache",
    "$HOME/",
    "${HOME}/",
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflow",
        default=str(DEFAULT_WORKFLOW),
        help="Path to CI workflow yaml file.",
    )
    return parser.parse_args(argv)


def _to_set(value: object) -> set[str]:
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    return set()


def _find_step(job: dict[str, object], *, name: str) -> dict[str, object] | None:
    steps = job.get("steps", [])
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        if str(step.get("name", "")).strip() == name:
            return step
    return None


def _iter_job_steps(job: dict[str, object]) -> list[dict[str, object]]:
    steps = job.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


def _multiline_entries(value: object) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _normalize_scalar(value: object) -> str:
    return str(value).strip().strip('"').strip("'")


def _alt_retry_job_name(job_id: str) -> str | None:
    if job_id.endswith("-hosted-retry"):
        return job_id[: -len("-hosted-retry")] + "-self-hosted-fallback"
    if job_id.endswith("-self-hosted-fallback"):
        return job_id[: -len("-self-hosted-fallback")] + "-hosted-retry"
    return None


def _resolve_job_with_retry_alias(
    jobs: dict[str, object],
    job_id: str,
) -> tuple[str, dict[str, object]] | tuple[None, None]:
    raw_job = jobs.get(job_id)
    if isinstance(raw_job, dict):
        return job_id, raw_job
    alt_job_id = _alt_retry_job_name(job_id)
    if alt_job_id is None:
        return None, None
    alt_job = jobs.get(alt_job_id)
    if isinstance(alt_job, dict):
        return alt_job_id, alt_job
    return None, None


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _is_dangerous_cache_env_value(value: object) -> bool:
    normalized = _normalize_scalar(value)
    if not normalized:
        return False
    if _contains_any(normalized, RUNNER_TEMP_TOKENS):
        return False
    if _contains_any(normalized, WORKSPACE_TOKENS):
        return True
    if _contains_any(normalized, HOME_TOKENS):
        return True
    if normalized.startswith(("~/", "./", ".\\", "../", "..\\")):
        return True
    if normalized.startswith("/"):
        return False
    if normalized.startswith("${{") or normalized.startswith("$"):
        return False
    return True


def _is_dangerous_workspace_cache_path(value: object) -> bool:
    normalized = _normalize_scalar(value)
    if not normalized:
        return False
    lowered = normalized.lower()
    if _contains_any(normalized, RUNNER_TEMP_TOKENS):
        return False
    if any(token in lowered for token in WORKSPACE_TOKENS):
        return "/.venv" in lowered or "/.cache" in lowered
    return lowered in {".venv", "./.venv", ".cache", "./.cache"} or lowered.startswith((".venv/", "./.venv/", ".cache/", "./.cache/"))


def _job_uses_hygiene_script(job: dict[str, object]) -> bool:
    return any(HYGIENE_SCRIPT_TOKEN in str(step.get("run", "")) for step in _iter_job_steps(job))


def _job_has_checkout_step(job: dict[str, object]) -> bool:
    return any(str(step.get("uses", "")).strip().startswith("actions/checkout@") for step in _iter_job_steps(job))


def _job_has_named_step(job: dict[str, object], *, name: str) -> bool:
    return _find_step(job, name=name) is not None


def _validate_self_hosted_job_hygiene(
    workflow_label: str,
    jobs: dict[str, object],
    *,
    failures: list[str],
    require_script_call: bool,
) -> None:
    for job_id, raw_job in jobs.items():
        if not isinstance(raw_job, dict) or not _is_self_hosted_shared_pool(raw_job.get("runs-on")):
            continue
        if not _iter_job_steps(raw_job) or not _job_has_checkout_step(raw_job):
            continue
        if require_script_call and not _job_uses_hygiene_script(raw_job):
            failures.append(f"{workflow_label} job {job_id} must call {HYGIENE_SCRIPT_TOKEN} before checkout on self-hosted runners")


def _validate_heavy_job_stage_hygiene(
    workflow_label: str,
    jobs: dict[str, object],
    *,
    failures: list[str],
    heavy_jobs: set[str],
) -> None:
    for job_id in sorted(heavy_jobs):
        raw_job = jobs.get(job_id)
        if not isinstance(raw_job, dict):
            continue
        if not _is_self_hosted_shared_pool(raw_job.get("runs-on")) or not _job_has_checkout_step(raw_job):
            continue
        if not _job_has_named_step(raw_job, name="Pre-checkout workspace hygiene"):
            failures.append(f"{workflow_label} heavy job {job_id} must define 'Pre-checkout workspace hygiene'")
        if not _job_has_named_step(raw_job, name="Post-checkout workspace hygiene"):
            failures.append(f"{workflow_label} heavy job {job_id} must define 'Post-checkout workspace hygiene'")


def _validate_dual_lane_resolver(
    jobs: dict[str, object],
    *,
    failures: list[str],
    resolver_job: str,
    hosted_job: str,
    retry_job: str,
    shared_needs_prefix: set[str],
) -> None:
    resolver = jobs.get(resolver_job, {})
    hosted = jobs.get(hosted_job, {})
    actual_retry_job_id, retry = _resolve_job_with_retry_alias(jobs, retry_job)
    if not isinstance(resolver, dict):
        failures.append(f"{resolver_job} resolver job missing")
        return
    if not isinstance(hosted, dict):
        failures.append(f"{hosted_job} hosted-primary job missing")
        return
    if not isinstance(retry, dict) or actual_retry_job_id is None:
        failures.append(f"{retry_job} hosted-retry job missing")
        return
    resolver_needs = _to_set(resolver.get("needs"))
    expected_resolver_needs = {hosted_job, actual_retry_job_id} | shared_needs_prefix
    if resolver_needs != expected_resolver_needs:
        failures.append(f"{resolver_job} resolver needs must equal {sorted(expected_resolver_needs)}")
    if not _is_github_hosted(hosted.get("runs-on")):
        failures.append(f"{hosted_job} must run on {GITHUB_HOSTED_PRIMARY}")
    if actual_retry_job_id.endswith("-self-hosted-fallback"):
        if not _is_self_hosted_shared_pool(retry.get("runs-on")):
            failures.append(f"{actual_retry_job_id} must run on [self-hosted, shared-pool]")
    elif not _is_github_hosted(retry.get("runs-on")):
        failures.append(f"{actual_retry_job_id} must run on {GITHUB_HOSTED_PRIMARY}")
    if not _is_github_hosted_or_self_hosted(resolver.get("runs-on")):
        failures.append(f"{resolver_job} resolver job must run on {GITHUB_HOSTED_PRIMARY} or [self-hosted, shared-pool]")


def _validate_job_needs_superset(
    jobs: dict[str, object],
    *,
    failures: list[str],
    job_id: str,
    expected_needs: set[str],
) -> None:
    actual_job_id, job = _resolve_job_with_retry_alias(jobs, job_id)
    if not isinstance(job, dict) or actual_job_id is None:
        failures.append(f"{job_id} job missing")
        return
    actual_needs = _to_set(job.get("needs"))
    if not expected_needs.issubset(actual_needs):
        failures.append(f"{actual_job_id}.needs must include {sorted(expected_needs)}")


def _maybe_validate_dual_lane_resolver(
    jobs: dict[str, object],
    *,
    failures: list[str],
    resolver_job: str,
    hosted_job: str,
    retry_job: str,
    shared_needs_prefix: set[str],
) -> None:
    alt_retry_job = _alt_retry_job_name(retry_job)
    retry_candidates = (retry_job,) if alt_retry_job is None else (retry_job, alt_retry_job)
    if not any(job_id in jobs for job_id in (resolver_job, hosted_job, *retry_candidates)):
        return
    _validate_dual_lane_resolver(
        jobs,
        failures=failures,
        resolver_job=resolver_job,
        hosted_job=hosted_job,
        retry_job=retry_job,
        shared_needs_prefix=shared_needs_prefix,
    )


def _validate_cache_env_and_paths(
    workflow_label: str,
    jobs: dict[str, object],
    *,
    failures: list[str],
) -> None:
    for job_id, raw_job in jobs.items():
        if not isinstance(raw_job, dict):
            continue

        def _check_env(env_value: object, owner: str) -> None:
            if not isinstance(env_value, dict):
                return
            for env_name in ("PRE_COMMIT_HOME", "XDG_CACHE_HOME"):
                if env_name not in env_value:
                    continue
                if _is_dangerous_cache_env_value(env_value.get(env_name)):
                    failures.append(
                        f"{workflow_label} {owner} sets {env_name} to unsafe cache path '{_normalize_scalar(env_value.get(env_name))}'"
                    )

        _check_env(raw_job.get("env"), f"job {job_id}")

        for idx, step in enumerate(_iter_job_steps(raw_job), start=1):
            _check_env(step.get("env"), f"job {job_id}.steps[{idx}]")
            uses_value = str(step.get("uses", "")).strip()
            if not uses_value.startswith("actions/cache@"):
                continue
            with_value = step.get("with")
            if not isinstance(with_value, dict):
                continue
            for path_entry in _multiline_entries(with_value.get("path")):
                if _is_dangerous_workspace_cache_path(path_entry):
                    failures.append(
                        f"{workflow_label} job {job_id}.steps[{idx}] actions/cache path "
                        f"'{path_entry}' must not cache workspace-local temp env/cache directories"
                    )


def _workflow_on_value(data: dict[str, object]) -> object:
    if "on" in data:
        return data.get("on")
    # PyYAML (YAML 1.1) may parse key "on" as boolean True.
    return cast(dict[object, object], data).get(True)


def _write_permission_entries(permissions: object) -> list[str]:
    if not isinstance(permissions, dict):
        return []
    risky: list[str] = []
    for scope, raw_value in permissions.items():
        value = str(raw_value).strip().lower()
        if value in {"write", "write-all"}:
            risky.append(f"{scope}={raw_value}")
    return risky


def _validate_workflow_security_baseline(
    data: dict[str, object],
    *,
    workflow_label: str,
    failures: list[str],
) -> None:
    on_value = _workflow_on_value(data)
    if isinstance(on_value, dict) and "pull_request_target" in on_value:
        failures.append(f"{workflow_label} workflow.on must not include pull_request_target")

    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        failures.append(f"{workflow_label} missing top-level permissions mapping")
    else:
        if permissions.get("contents") != "read":
            failures.append(f"{workflow_label} permissions.contents must be read")
        workflow_write_entries = _write_permission_entries(permissions)
        if workflow_write_entries:
            failures.append(f"{workflow_label} top-level permissions must not grant write scopes: {', '.join(workflow_write_entries)}")

    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return
    for job_id, job in jobs.items():
        if not isinstance(job, dict) or "permissions" not in job:
            continue
        job_permissions = job.get("permissions")
        if not isinstance(job_permissions, dict):
            failures.append(f"{workflow_label} job {job_id} permissions must be a mapping")
            continue
        write_entries = _write_permission_entries(job_permissions)
        if job_id in {"build-ci-image", "build-runtime-image"}:
            allowed = {"packages=write", "id-token=write", "attestations=write", "artifact-metadata=write"}
            if set(write_entries).issubset(allowed):
                continue
        if write_entries:
            failures.append(f"{workflow_label} job {job_id} must not grant write scopes: {', '.join(write_entries)}")


def _runner_labels(value: object) -> set[str]:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    return set()


def _is_self_hosted_shared_pool(value: object) -> bool:
    labels = _runner_labels(value)
    return SELF_HOSTED_SHARED_POOL.issubset(labels)


def _is_github_hosted(value: object) -> bool:
    return _normalize_scalar(value) == GITHUB_HOSTED_PRIMARY


def _is_github_hosted_or_self_hosted(value: object) -> bool:
    return _is_github_hosted(value) or _is_self_hosted_shared_pool(value)


def _validate_pinned_actions(
    jobs: object,
    *,
    failures: list[str],
    workflow_label: str,
) -> None:
    def _validate_uses_reference(uses_value: str, location: str) -> None:
        normalized = uses_value.strip()
        if normalized.startswith("./") or normalized.startswith(".\\"):
            return
        if normalized.startswith("docker://"):
            if not DOCKER_IMAGE_USES.match(normalized):
                failures.append(f"{workflow_label} {location} uses '{normalized}' must pin docker image to sha256 digest")
            return
        if REMOTE_ACTION_USES_NO_REF.match(normalized):
            failures.append(f"{workflow_label} {location} uses '{normalized}' must pin to 40-char commit SHA")
            return
        match = REMOTE_ACTION_USES.match(normalized)
        if match and not PINNED_COMMIT_SHA.match(match.group("ref").strip()):
            failures.append(f"{workflow_label} {location} uses '{normalized}' must pin to 40-char commit SHA")

    if not isinstance(jobs, dict):
        return
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_uses = job.get("uses")
        if isinstance(job_uses, str):
            _validate_uses_reference(job_uses, f"job {job_id}")
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            continue
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue
            uses_value = step.get("uses")
            if not isinstance(uses_value, str):
                continue
            _validate_uses_reference(uses_value, f"job {job_id}.steps[{idx}]")


def _step_uses_checkout(step: dict[str, object]) -> bool:
    uses_value = step.get("uses")
    return isinstance(uses_value, str) and uses_value.strip().startswith("actions/checkout@")


def _is_runner_temp_backed(value: str) -> bool:
    normalized = value.strip()
    return any(token in normalized for token in RUNNER_TEMP_TOKENS)


def _is_dangerous_workspace_path(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    if _is_runner_temp_backed(normalized):
        return False
    if "${{ github.workspace }}" in normalized or "$GITHUB_WORKSPACE" in normalized:
        return True
    if normalized.startswith("~/.cache/pre-commit"):
        return True
    return WORKSPACE_CACHE_PATTERN.match(normalized) is not None


def _iter_env_mappings(job: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    env_maps: list[tuple[str, dict[str, object]]] = []
    job_env = job.get("env")
    if isinstance(job_env, dict):
        env_maps.append(("job env", job_env))
    steps = job.get("steps", [])
    if not isinstance(steps, list):
        return env_maps
    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        step_env = step.get("env")
        if isinstance(step_env, dict):
            env_maps.append((f"steps[{idx}] env", step_env))
    return env_maps


def _validate_workspace_hygiene_and_cache_paths(
    jobs: object,
    *,
    failures: list[str],
    workflow_label: str,
) -> None:
    if not isinstance(jobs, dict):
        return

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue

        for env_location, env_map in _iter_env_mappings(job):
            for key in WORKSPACE_ENV_KEYS:
                raw_value = env_map.get(key)
                if not isinstance(raw_value, str):
                    continue
                if _is_dangerous_workspace_path(raw_value):
                    failures.append(
                        f"{workflow_label} job {job_id} {env_location} {key} must use runner.temp-backed path, got '{raw_value.strip()}'"
                    )

        steps = job.get("steps", [])
        if not isinstance(steps, list):
            continue

        checkout_idx: int | None = None
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            if _step_uses_checkout(step):
                checkout_idx = idx
                checkout_with = step.get("with")
                if isinstance(checkout_with, dict) and checkout_with.get("clean") is not False:
                    failures.append(f"{workflow_label} job {job_id} checkout on self-hosted runner must set clean: false")
                break

        if _is_self_hosted_shared_pool(job.get("runs-on")) and checkout_idx is not None:
            pre_checkout_steps = steps[:checkout_idx]
            if not any(
                isinstance(step, dict) and 'rm -rf "$GITHUB_WORKSPACE/.git"' in str(step.get("run", "")) for step in pre_checkout_steps
            ):
                failures.append(f"{workflow_label} job {job_id} must clear $GITHUB_WORKSPACE/.git before checkout")

            if not any(isinstance(step, dict) and HYGIENE_SCRIPT_SNIPPET in str(step.get("run", "")) for step in steps[checkout_idx + 1 :]):
                failures.append(f"{workflow_label} job {job_id} must invoke gha_self_hosted_hygiene.sh after checkout")

        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue
            if str(step.get("uses", "")).strip() != "actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830":
                continue
            raw_path = step.get("with", {})
            if not isinstance(raw_path, dict):
                continue
            path_value = raw_path.get("path")
            if not isinstance(path_value, str):
                continue
            for line in path_value.splitlines():
                candidate = line.strip()
                if not candidate:
                    continue
                if _is_dangerous_workspace_path(candidate):
                    failures.append(
                        f"{workflow_label} job {job_id}.steps[{idx}] actions/cache path must not target workspace temp dir '{candidate}'"
                    )


def _is_runner_temp_value(value: str) -> bool:
    normalized = value.strip()
    return "runner.temp" in normalized or "$RUNNER_TEMP" in normalized or "${RUNNER_TEMP}" in normalized


def _is_workspace_relative_temp_path(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    if _is_runner_temp_value(normalized):
        return False
    if normalized.startswith("~/.cache/pre-commit"):
        return True
    if normalized in WORKSPACE_CACHE_PATTERNS:
        return True
    if normalized.startswith("${{ github.workspace }}/") or normalized.startswith("$GITHUB_WORKSPACE/"):
        return any(token in normalized for token in WORKSPACE_CACHE_PATTERNS)
    return False


def _validate_cache_hygiene(
    workflow_label: str,
    jobs: object,
    *,
    failures: list[str],
    require_script_call: bool = False,
) -> None:
    if not isinstance(jobs, dict):
        return

    script_call_found = False
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            continue
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue
            run_value = str(step.get("run", ""))
            if SELF_HOSTED_HYGIENE_SCRIPT in run_value:
                script_call_found = True

            step_env = step.get("env")
            if isinstance(step_env, dict):
                for env_name in ("PRE_COMMIT_HOME", "XDG_CACHE_HOME"):
                    raw_value = step_env.get(env_name)
                    if raw_value is not None and _is_workspace_relative_temp_path(str(raw_value)):
                        failures.append(
                            f"{workflow_label} job {job_id}.steps[{idx}] env {env_name} "
                            f"must not point to workspace-relative cache path: {raw_value}"
                        )

            uses_value = str(step.get("uses", "")).strip()
            if not uses_value.startswith("actions/cache@"):
                continue
            with_block = step.get("with")
            if not isinstance(with_block, dict):
                continue
            raw_path = str(with_block.get("path", "")).strip()
            if not raw_path:
                continue
            for line in raw_path.splitlines():
                candidate = line.strip()
                if not candidate:
                    continue
                if _is_workspace_relative_temp_path(candidate):
                    failures.append(
                        f"{workflow_label} job {job_id}.steps[{idx}] cache path must not store workspace temp environment: {candidate}"
                    )

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_env = job.get("env")
        if not isinstance(job_env, dict):
            continue
        for env_name in ("PRE_COMMIT_HOME", "XDG_CACHE_HOME"):
            raw_value = job_env.get(env_name)
            if raw_value is not None and _is_workspace_relative_temp_path(str(raw_value)):
                failures.append(
                    f"{workflow_label} job {job_id} env {env_name} must not point to workspace-relative cache path: {raw_value}"
                )

    if require_script_call and not script_call_found:
        failures.append(f"{workflow_label} must call {SELF_HOSTED_HYGIENE_SCRIPT} in at least one step")


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    workflow_path = Path(args.workflow).resolve()
    if not workflow_path.exists():
        print(f"❌ ci-hardening: workflow file not found: {workflow_path}")
        return 2

    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("❌ ci-hardening: workflow yaml root must be a mapping")
        return 1

    failures: list[str] = []
    workflow_text = workflow_path.read_text(encoding="utf-8")

    _validate_workflow_security_baseline(data, workflow_label=workflow_path.name, failures=failures)

    on_value = _workflow_on_value(data)
    if not isinstance(on_value, dict) or "merge_group" not in on_value:
        failures.append(f"{workflow_path.name} workflow.on must declare merge_group trigger")

    concurrency = data.get("concurrency")
    if not isinstance(concurrency, dict):
        failures.append("missing top-level concurrency mapping")
    else:
        group = str(concurrency.get("group", ""))
        if "${{ github.workflow }}" not in group or "${{ github.ref }}" not in group:
            failures.append("concurrency.group must include github.workflow and github.ref")
        cancel_in_progress = concurrency.get("cancel-in-progress")
        if cancel_in_progress is True:
            pass
        elif isinstance(cancel_in_progress, str) and "github.event_name" in cancel_in_progress:
            # Allow event-aware cancel policy, e.g. keep workflow_dispatch runs from being canceled by push runs.
            pass
        else:
            failures.append("concurrency.cancel-in-progress must be true or an expression based on github.event_name")

    jobs = data.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        failures.append("missing jobs mapping")
        jobs = {}

    required_jobs = {
        "change-detection",
        "fork-pr-safety-gate",
        "commit-message-lint",
        "atomic-commit-gate",
        "secrets-supply-chain-gate",
        "ci-hardening-gate",
        "lint-backend",
        "lint-frontend",
        "webui-build-test",
        "quality-gate-full",
        "packaging-gate",
        "mutation-canary-gate",
        "live-smoke-preflight",
        "functional-gate",
        "test",
        "evidence-bundle",
        "cleanup-resources",
    }
    missing_required_jobs = sorted(job for job in required_jobs if job not in jobs)
    if missing_required_jobs:
        failures.append(f"missing required jobs: {', '.join(missing_required_jobs)}")

    expected_hosted_jobs = {
        "change-detection",
        "fork-pr-safety-gate",
        "commit-message-lint",
        "atomic-commit-gate",
        "secrets-supply-chain-gate",
        "ci-hardening-gate",
        "lint-backend",
        "lint-frontend",
        "webui-build-test",
        "quality-gate-full",
        "packaging-gate",
        "mutation-canary-gate",
        "live-smoke-preflight",
        "functional-gate",
        "test",
        "evidence-bundle",
        "cleanup-resources",
        "change-detection-hosted-primary",
        "change-detection-hosted-retry",
        "commit-message-lint-hosted-primary",
        "commit-message-lint-hosted-retry",
        "atomic-commit-gate-hosted-primary",
        "atomic-commit-gate-hosted-retry",
        "secrets-supply-chain-gate-hosted-primary",
        "secrets-supply-chain-gate-hosted-retry",
        "ci-hardening-gate-hosted-primary",
        "ci-hardening-gate-hosted-retry",
        "lint-backend-hosted-primary",
        "lint-backend-hosted-retry",
        "lint-frontend-hosted-primary",
        "lint-frontend-hosted-retry",
        "webui-build-test-hosted-primary",
        "webui-build-test-hosted-retry",
        "quality-gate-full-hosted-primary",
        "quality-gate-full-hosted-retry",
        "packaging-gate-hosted-primary",
        "packaging-gate-hosted-retry",
        "mutation-canary-gate-hosted-primary",
        "mutation-canary-gate-hosted-retry",
        "live-smoke-preflight-hosted-primary",
        "live-smoke-preflight-hosted-retry",
        "functional-gate-hosted-primary",
        "functional-gate-hosted-retry",
        "test-hosted-primary",
        "test-hosted-retry",
    }
    expected_self_hosted_jobs: set[str] = set()

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            failures.append(f"job {job_id} must be a mapping")
            continue
        timeout = job.get("timeout-minutes")
        if not isinstance(timeout, int) or timeout < 1 or timeout > 120:
            failures.append(f"job {job_id} must set timeout-minutes in [1,120]")
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            failures.append(f"job {job_id}.steps must be a list")
            continue
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                failures.append(f"job {job_id}.steps[{idx}] must be a mapping")
                continue
        if job_id in expected_hosted_jobs and _normalize_scalar(job.get("runs-on")) != GITHUB_HOSTED_PRIMARY:
            failures.append(f"job {job_id} must run on {GITHUB_HOSTED_PRIMARY}")
        if job_id in expected_self_hosted_jobs and not _is_self_hosted_shared_pool(job.get("runs-on")):
            failures.append(f"job {job_id} must run on [self-hosted, shared-pool]")
        if job_id.endswith("-self-hosted-fallback") or job_id.endswith("-hosted-retry"):
            if not _is_github_hosted_or_self_hosted(job.get("runs-on")):
                failures.append(f"fallback job {job_id} must run on {GITHUB_HOSTED_PRIMARY} or [self-hosted, shared-pool]")
            fallback_if = str(job.get("if", ""))
            if "outputs.entered != 'true'" not in fallback_if and "result != 'success'" not in fallback_if:
                failures.append(f"fallback job {job_id} must guard on hosted entry sentinel or hosted-primary non-success result")
        if job_id.endswith("-hosted-primary") and _normalize_scalar(job.get("runs-on")) != GITHUB_HOSTED_PRIMARY:
            failures.append(f"hosted primary job {job_id} must run on {GITHUB_HOSTED_PRIMARY}")

    forbidden_runner_registration = ("config.sh", "./run.sh", "remove.sh")
    for token in forbidden_runner_registration:
        if token in workflow_text:
            failures.append(f"ci.yml must not contain runner registration command token: {token}")

    _validate_pinned_actions(jobs, failures=failures, workflow_label=workflow_path.name)

    build_ci_image = jobs.get("build-ci-image", {})
    if isinstance(build_ci_image, dict):
        build_if = str(build_ci_image.get("if", "")).strip()
        if (
            "github.event_name != 'pull_request'" not in build_if
            or "github.event.pull_request.head.repo.full_name == github.repository" not in build_if
        ):
            failures.append("build-ci-image must skip untrusted fork PRs and only run automatically for same-repo pull requests")
    _validate_heavy_job_stage_hygiene(
        workflow_path.name,
        jobs,
        failures=failures,
        heavy_jobs={
            "lint-backend",
            "lint-frontend",
            "webui-build-test-hosted-retry",
            "packaging-gate-hosted-retry",
            "webui-build-test",
            "quality-gate-full",
            "mutation-canary-gate",
            "live-smoke-preflight",
            "functional-gate",
            "test",
            "evidence-bundle",
            "cleanup-resources",
        },
    )

    if "GITLEAKS_EXPECTED_SHA256" not in workflow_text:
        failures.append("ci.yml must pin gitleaks archive checksum via GITLEAKS_EXPECTED_SHA256")
    if "gitleaks_" in workflow_text and "_checksums.txt" in workflow_text:
        failures.append("ci.yml must not trust gitleaks checksums.txt from the same download origin")
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []):
            if not isinstance(step, dict):
                continue
            run_text = str(step.get("run", ""))
            if "tooling/scripts/fetch_upstream_artifact.py" not in run_text:
                continue
            if "--upstream-id gitleaks-release-binary" not in run_text:
                failures.append(f"{job_id}: must fetch gitleaks through registered upstream-id gitleaks-release-binary")
            if "--expected-sha256" not in run_text:
                failures.append(f"{job_id}: must pass --expected-sha256 when fetching gitleaks through fetch_upstream_artifact.py")
            if "--url " in run_text or "--output " in run_text:
                failures.append(f"{job_id}: must not bypass fetch_upstream_artifact.py contracts with --url/--output arguments")

    quality_needs = _to_set(jobs.get("quality-gate-full-hosted-primary", {}).get("needs"))
    if not {"commit-message-lint", "atomic-commit-gate", "secrets-supply-chain-gate"}.issubset(quality_needs):
        failures.append(
            "quality-gate-full-hosted-primary.needs must include commit-message-lint/atomic-commit-gate/secrets-supply-chain-gate"
        )

    _validate_dual_lane_resolver(
        jobs,
        failures=failures,
        resolver_job="webui-build-test",
        hosted_job="webui-build-test-hosted-primary",
        retry_job="webui-build-test-hosted-retry",
        shared_needs_prefix={"change-detection"},
    )

    _maybe_validate_dual_lane_resolver(
        jobs,
        failures=failures,
        resolver_job="lint-backend",
        hosted_job="lint-backend-hosted-primary",
        retry_job="lint-backend-hosted-retry",
        shared_needs_prefix={"change-detection"},
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="lint-backend-hosted-primary",
        expected_needs={"change-detection", "build-ci-image"},
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="lint-backend-hosted-retry",
        expected_needs={"change-detection", "build-ci-image", "lint-backend-hosted-primary"},
    )

    _maybe_validate_dual_lane_resolver(
        jobs,
        failures=failures,
        resolver_job="lint-frontend",
        hosted_job="lint-frontend-hosted-primary",
        retry_job="lint-frontend-hosted-retry",
        shared_needs_prefix={"change-detection"},
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="lint-frontend-hosted-primary",
        expected_needs={"change-detection", "build-ci-image"},
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="lint-frontend-hosted-retry",
        expected_needs={"change-detection", "build-ci-image", "lint-frontend-hosted-primary"},
    )

    _maybe_validate_dual_lane_resolver(
        jobs,
        failures=failures,
        resolver_job="quality-gate-full",
        hosted_job="quality-gate-full-hosted-primary",
        retry_job="quality-gate-full-hosted-retry",
        shared_needs_prefix={"change-detection"},
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="quality-gate-full-hosted-primary",
        expected_needs={
            "change-detection",
            "commit-message-lint",
            "atomic-commit-gate",
            "secrets-supply-chain-gate",
            "ci-hardening-gate",
            "build-ci-image",
        },
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="quality-gate-full-hosted-retry",
        expected_needs={
            "change-detection",
            "commit-message-lint",
            "atomic-commit-gate",
            "secrets-supply-chain-gate",
            "ci-hardening-gate",
            "build-ci-image",
            "quality-gate-full-hosted-primary",
        },
    )

    _maybe_validate_dual_lane_resolver(
        jobs,
        failures=failures,
        resolver_job="mutation-canary-gate",
        hosted_job="mutation-canary-gate-hosted-primary",
        retry_job="mutation-canary-gate-hosted-retry",
        shared_needs_prefix={"change-detection"},
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="mutation-canary-gate-hosted-primary",
        expected_needs={
            "change-detection",
            "commit-message-lint",
            "atomic-commit-gate",
            "secrets-supply-chain-gate",
            "lint-backend",
            "lint-frontend",
            "ci-hardening-gate",
            "quality-gate-full",
            "build-ci-image",
        },
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="mutation-canary-gate-hosted-retry",
        expected_needs={
            "change-detection",
            "commit-message-lint",
            "atomic-commit-gate",
            "secrets-supply-chain-gate",
            "lint-backend",
            "lint-frontend",
            "ci-hardening-gate",
            "quality-gate-full",
            "build-ci-image",
            "mutation-canary-gate-hosted-primary",
        },
    )

    _maybe_validate_dual_lane_resolver(
        jobs,
        failures=failures,
        resolver_job="live-smoke-preflight",
        hosted_job="live-smoke-preflight-hosted-primary",
        retry_job="live-smoke-preflight-hosted-retry",
        shared_needs_prefix=set(),
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="live-smoke-preflight-hosted-primary",
        expected_needs={"fork-pr-safety-gate", "build-ci-image"},
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="live-smoke-preflight-hosted-retry",
        expected_needs={"fork-pr-safety-gate", "build-ci-image", "live-smoke-preflight-hosted-primary"},
    )
    for live_job_id in ("live-smoke-preflight-hosted-primary", "live-smoke-preflight-hosted-retry"):
        live_job = jobs.get(live_job_id, {})
        if not isinstance(live_job, dict):
            failures.append(f"{live_job_id} missing")
            continue
        if str(live_job.get("environment", "")).strip() != "owner-approved-sensitive":
            failures.append(f"{live_job_id} must use environment owner-approved-sensitive")
        live_if = str(live_job.get("if", "")).strip()
        if "github.event_name == 'workflow_dispatch'" not in live_if:
            failures.append(f"{live_job_id} must be workflow_dispatch-only")

    _maybe_validate_dual_lane_resolver(
        jobs,
        failures=failures,
        resolver_job="functional-gate",
        hosted_job="functional-gate-hosted-primary",
        retry_job="functional-gate-hosted-retry",
        shared_needs_prefix={"change-detection"},
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="functional-gate-hosted-primary",
        expected_needs={
            "change-detection",
            "commit-message-lint",
            "atomic-commit-gate",
            "secrets-supply-chain-gate",
            "quality-gate-full",
            "mutation-canary-gate",
            "build-ci-image",
        },
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="functional-gate-hosted-retry",
        expected_needs={
            "change-detection",
            "commit-message-lint",
            "atomic-commit-gate",
            "secrets-supply-chain-gate",
            "quality-gate-full",
            "mutation-canary-gate",
            "build-ci-image",
            "functional-gate-hosted-primary",
        },
    )

    _maybe_validate_dual_lane_resolver(
        jobs,
        failures=failures,
        resolver_job="test",
        hosted_job="test-hosted-primary",
        retry_job="test-hosted-retry",
        shared_needs_prefix={"change-detection"},
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="test-hosted-primary",
        expected_needs={
            "change-detection",
            "commit-message-lint",
            "atomic-commit-gate",
            "secrets-supply-chain-gate",
            "lint-backend",
            "lint-frontend",
            "webui-build-test",
            "ci-hardening-gate",
            "quality-gate-full",
            "mutation-canary-gate",
            "functional-gate",
            "build-ci-image",
        },
    )
    _validate_job_needs_superset(
        jobs,
        failures=failures,
        job_id="test-hosted-retry",
        expected_needs={
            "change-detection",
            "commit-message-lint",
            "atomic-commit-gate",
            "secrets-supply-chain-gate",
            "lint-backend",
            "lint-frontend",
            "webui-build-test",
            "ci-hardening-gate",
            "quality-gate-full",
            "mutation-canary-gate",
            "functional-gate",
            "build-ci-image",
            "test-hosted-primary",
        },
    )

    evidence_needs = _to_set(jobs.get("evidence-bundle", {}).get("needs"))
    if "quality-gate-full" not in evidence_needs or "functional-gate" not in evidence_needs or "webui-build-test" not in evidence_needs:
        failures.append("evidence-bundle.needs must include quality-gate-full, functional-gate, and webui-build-test")

    def _job_has_entry(job_id: str, snippet: str) -> bool:
        job = jobs.get(job_id, {})
        if not isinstance(job, dict):
            return False
        for step in job.get("steps", []) or []:
            if isinstance(step, dict) and snippet in str(step.get("run", "")):
                return True
        return False

    if not (
        _job_has_entry("quality-gate-full-hosted-primary", "quality_gate.sh")
        or _job_has_entry("quality-gate-full-hosted-retry", "quality_gate.sh")
        or _job_has_entry("quality-gate-full-self-hosted-fallback", "quality_gate.sh")
    ):
        failures.append("quality-gate-full hosted primary/retry lanes must run quality_gate.sh")
    _validate_dual_lane_resolver(
        jobs,
        failures=failures,
        resolver_job="packaging-gate",
        hosted_job="packaging-gate-hosted-primary",
        retry_job="packaging-gate-hosted-retry",
        shared_needs_prefix={"change-detection"},
    )
    if not _job_has_entry("packaging-gate-hosted-primary", "docs_smoke.sh --install-smoke"):
        failures.append("packaging-gate-hosted-primary must run docs_smoke.sh --install-smoke")
    if not (
        _job_has_entry("packaging-gate-hosted-retry", "docs_smoke.sh --install-smoke")
        or _job_has_entry("packaging-gate-self-hosted-fallback", "docs_smoke.sh --install-smoke")
    ):
        failures.append("packaging-gate hosted retry/fallback lane must run docs_smoke.sh --install-smoke")
    if not (
        _job_has_entry("functional-gate-hosted-primary", "functional_gate.sh")
        or _job_has_entry("functional-gate-hosted-retry", "functional_gate.sh")
        or _job_has_entry("functional-gate-self-hosted-fallback", "functional_gate.sh")
    ):
        failures.append("functional-gate hosted primary/retry lanes must run functional_gate.sh")
    has_webui_test = (
        _job_has_entry(
            "webui-build-test-hosted-primary",
            "npm --prefix apps/webui run test",
        )
        or _job_has_entry(
            "webui-build-test-hosted-retry",
            "npm --prefix apps/webui run test",
        )
        or _job_has_entry(
            "webui-build-test-self-hosted-fallback",
            "npm --prefix apps/webui run test",
        )
    )
    has_webui_build = (
        _job_has_entry(
            "webui-build-test-hosted-primary",
            "npm --prefix apps/webui run build",
        )
        or _job_has_entry(
            "webui-build-test-hosted-retry",
            "npm --prefix apps/webui run build",
        )
        or _job_has_entry(
            "webui-build-test-self-hosted-fallback",
            "npm --prefix apps/webui run build",
        )
    )
    if not has_webui_test or not has_webui_build:
        failures.append(
            "webui-build-test hosted primary/retry lanes must run npm --prefix apps/webui run test and npm --prefix apps/webui run build"
        )

    lint_frontend_job = jobs.get("lint-frontend-hosted-primary", {})
    if isinstance(lint_frontend_job, dict):
        lint_step = _find_step(lint_frontend_job, name="Frontend lint gate")
        if lint_step is None:
            failures.append("lint-frontend-hosted-primary must include 'Frontend lint gate' step")
        else:
            lint_step_env = lint_step.get("env")
            if not isinstance(lint_step_env, dict):
                failures.append("lint-frontend-hosted-primary 'Frontend lint gate' must define env mapping")
            else:
                lint_key_ref = str(lint_step_env.get("GEMINI_API_KEY", "")).strip()
                if lint_key_ref != "${{ secrets.GEMINI_API_KEY }}":
                    failures.append("lint-frontend-hosted-primary 'Frontend lint gate' must set GEMINI_API_KEY from secrets.GEMINI_API_KEY")
                lint_model_ref = str(lint_step_env.get("GEMINI_UI_AUDIT_MODEL", "")).strip()
                if "vars.GEMINI_UI_AUDIT_MODEL" not in lint_model_ref:
                    failures.append(
                        "lint-frontend-hosted-primary 'Frontend lint gate' must set GEMINI_UI_AUDIT_MODEL from repository variables"
                    )
        semantic_step = _find_step(lint_frontend_job, name="Semantic UI/UX audit gate (Gemini)")
        if semantic_step is not None:
            step_env = semantic_step.get("env")
            if not isinstance(step_env, dict):
                failures.append("lint-frontend-hosted-primary semantic UI/UX step must define env mapping")
            else:
                gemini_api_key_ref = str(step_env.get("GEMINI_API_KEY", "")).strip()
                if gemini_api_key_ref != "${{ secrets.GEMINI_API_KEY }}":
                    failures.append("lint-frontend-hosted-primary semantic UI/UX step must set GEMINI_API_KEY from secrets.GEMINI_API_KEY")
                model_ref = str(step_env.get("GEMINI_UI_AUDIT_MODEL", "")).strip()
                if "vars.GEMINI_UI_AUDIT_MODEL" not in model_ref:
                    failures.append(
                        "lint-frontend-hosted-primary semantic UI/UX step must set GEMINI_UI_AUDIT_MODEL from repository variables"
                    )

    workflows_dir = workflow_path.parent
    reusable_build_path = workflows_dir / "reusable-build-runtime-image.yml"
    if reusable_build_path.exists():
        reusable_data = yaml.safe_load(reusable_build_path.read_text(encoding="utf-8"))
        reusable_jobs = reusable_data.get("jobs", {}) if isinstance(reusable_data, dict) else {}
        if isinstance(reusable_data, dict):
            _validate_workflow_security_baseline(reusable_data, workflow_label=reusable_build_path.name, failures=failures)
        _validate_pinned_actions(reusable_jobs, failures=failures, workflow_label=reusable_build_path.name)
    precommit_path = workflows_dir / "pre-commit.yml"
    if precommit_path.exists():
        pre_data = yaml.safe_load(precommit_path.read_text(encoding="utf-8"))
        pre_jobs = pre_data.get("jobs", {}) if isinstance(pre_data, dict) else {}
        if isinstance(pre_data, dict):
            _validate_workflow_security_baseline(pre_data, workflow_label=precommit_path.name, failures=failures)
            if "build-ci-image" in pre_jobs and not isinstance(pre_data.get("concurrency"), dict):
                failures.append("pre-commit.yml must define top-level concurrency")
        _validate_pinned_actions(pre_jobs, failures=failures, workflow_label=precommit_path.name)
        if isinstance(pre_jobs, dict):
            build_job = pre_jobs.get("build-ci-image", {})
            uses_value = str(build_job.get("uses", "")).strip() if isinstance(build_job, dict) else ""
            if build_job and (not isinstance(build_job, dict) or uses_value != "./.github/workflows/reusable-build-runtime-image.yml"):
                failures.append("pre-commit.yml build-ci-image must use ./.github/workflows/reusable-build-runtime-image.yml")
            _validate_workspace_hygiene_and_cache_paths(
                pre_jobs,
                failures=failures,
                workflow_label=precommit_path.name,
            )
            build_if = str(build_job.get("if", "")).strip() if isinstance(build_job, dict) else ""
            if build_job and (
                not build_if
                or "github.event_name != 'pull_request'" not in build_if
                or "github.event.pull_request.head.repo.full_name == github.repository" not in build_if
            ):
                failures.append("pre-commit.yml build-ci-image must skip untrusted fork PRs")
            pre_primary = pre_jobs.get("pre-commit-hosted-primary", {})
            if not isinstance(pre_primary, dict) or not _is_github_hosted(pre_primary.get("runs-on")):
                failures.append("pre-commit-hosted-primary must run on ubuntu-latest")
            _, pre_retry = _resolve_job_with_retry_alias(pre_jobs, "pre-commit-hosted-retry")
            if not isinstance(pre_retry, dict) or not _is_github_hosted(pre_retry.get("runs-on")):
                failures.append("pre-commit-hosted-retry must run on ubuntu-latest")
            pre_resolver = pre_jobs.get("pre-commit", {})
            if not isinstance(pre_resolver, dict) or not _is_github_hosted(pre_resolver.get("runs-on")):
                failures.append("pre-commit resolver job must run on ubuntu-latest")
            precommit_text = precommit_path.read_text(encoding="utf-8")
            if "GHCR_PUSH_TOKEN" in precommit_text:
                failures.append("pre-commit.yml must not reference GHCR_PUSH_TOKEN")
            for token in forbidden_runner_registration:
                if token in precommit_text:
                    failures.append(f"pre-commit.yml must not contain runner registration command token: {token}")
            for required_snippet in ("bash tooling/runtime/bootstrap_env.sh", "pre-commit run --all-files"):
                if required_snippet not in precommit_text:
                    failures.append(f"pre-commit.yml must keep {required_snippet} in the hosted path")

    live_path = workflows_dir / "live-integration.yml"
    if live_path.exists():
        live_data = yaml.safe_load(live_path.read_text(encoding="utf-8"))
        live_jobs = live_data.get("jobs", {}) if isinstance(live_data, dict) else {}
        if isinstance(live_data, dict):
            _validate_workflow_security_baseline(live_data, workflow_label=live_path.name, failures=failures)
            if "build-ci-image" in live_jobs and not isinstance(live_data.get("concurrency"), dict):
                failures.append("live-integration.yml must define top-level concurrency")
        _validate_pinned_actions(live_jobs, failures=failures, workflow_label=live_path.name)
        live_job = live_jobs.get("live-tests", {}) if isinstance(live_jobs, dict) else {}
        if isinstance(live_jobs, dict):
            build_job = live_jobs.get("build-ci-image", {})
            uses_value = str(build_job.get("uses", "")).strip() if isinstance(build_job, dict) else ""
            if build_job and (not isinstance(build_job, dict) or uses_value != "./.github/workflows/reusable-build-runtime-image.yml"):
                failures.append("live-integration.yml build-ci-image must use ./.github/workflows/reusable-build-runtime-image.yml")
            _validate_workspace_hygiene_and_cache_paths(
                live_jobs,
                failures=failures,
                workflow_label=live_path.name,
            )
        live_runs_on = live_job.get("runs-on") if isinstance(live_job, dict) else None
        if not isinstance(live_job, dict) or str(live_runs_on).strip() != "ubuntu-latest":
            failures.append("live-integration live-tests must run on ubuntu-latest")
        if isinstance(live_job, dict) and str(live_job.get("environment", "")).strip() != "owner-approved-sensitive":
            failures.append("live-integration live-tests must use environment owner-approved-sensitive")
        live_text = live_path.read_text(encoding="utf-8")
        for token in forbidden_runner_registration:
            if token in live_text:
                failures.append(f"live-integration.yml must not contain runner registration command token: {token}")

    mutation_path = workflows_dir / "mutation-manual.yml"
    if mutation_path.exists():
        mutation_data = yaml.safe_load(mutation_path.read_text(encoding="utf-8"))
        mutation_jobs = mutation_data.get("jobs", {}) if isinstance(mutation_data, dict) else {}
        if isinstance(mutation_data, dict):
            _validate_workflow_security_baseline(mutation_data, workflow_label=mutation_path.name, failures=failures)
        _validate_pinned_actions(mutation_jobs, failures=failures, workflow_label=mutation_path.name)
        if isinstance(mutation_jobs, dict):
            build_job = mutation_jobs.get("build-ci-image", {})
            uses_value = str(build_job.get("uses", "")).strip() if isinstance(build_job, dict) else ""
            if build_job and (not isinstance(build_job, dict) or uses_value != "./.github/workflows/reusable-build-runtime-image.yml"):
                failures.append("mutation-manual.yml build-ci-image must use ./.github/workflows/reusable-build-runtime-image.yml")
            _validate_workspace_hygiene_and_cache_paths(
                mutation_jobs,
                failures=failures,
                workflow_label=mutation_path.name,
            )
            for mutation_job_id in ("python-mutmut", "js-stryker", "rust-cargo-mutants"):
                mutation_job = mutation_jobs.get(mutation_job_id, {})
                if not isinstance(mutation_job, dict) or not _is_github_hosted(mutation_job.get("runs-on")):
                    failures.append(f"mutation-manual.yml job {mutation_job_id} must run on ubuntu-latest")
        mutation_text = mutation_path.read_text(encoding="utf-8")
        if "GHCR_PUSH_TOKEN" in mutation_text:
            failures.append("mutation-manual.yml must not reference GHCR_PUSH_TOKEN")
        for token in forbidden_runner_registration:
            if token in mutation_text:
                failures.append(f"mutation-manual.yml must not contain runner registration command token: {token}")

    if failures:
        print("❌ ci-hardening: failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("✅ ci-hardening: passed")
    print(f"- workflow: {workflow_path}")
    print(f"- jobs: {len(jobs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
