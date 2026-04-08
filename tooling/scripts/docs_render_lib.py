#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_REGISTRY_PATH = REPO_ROOT / "contracts" / "runtime" / "env_contract_registry.yaml"
REQUIRED_CHECKS_POLICY_PATH = REPO_ROOT / "contracts" / "governance" / "required_checks_policy.yaml"
DOCS_RENDER_MANIFEST_PATH = REPO_ROOT / "contracts" / "docs" / "docs_render_manifest.yaml"
DOCS_NAV_REGISTRY_PATH = REPO_ROOT / "contracts" / "docs" / "docs_nav_registry.yaml"
OPENAPI_CONTRACT_PATH = REPO_ROOT / "contracts" / "api" / "web_api.openapi.yaml"

GENERATED_BLOCK_PATTERN = re.compile(
    r"<!-- BEGIN GENERATED: (?P<block_id>[a-z0-9-]+) -->.*?<!-- END GENERATED: (?P=block_id) -->",
    re.S,
)
METHOD_ORDER = {"GET": 0, "POST": 1, "PATCH": 2, "DELETE": 3}
SECTION_LABELS = {
    "required": "required",
    "runtime_optional": "runtime-optional",
    "observability_context": "runtime-optional (observability context)",
    "ci_only": "ci-only",
    "test_only": "test-only",
}


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping yaml: {path}")
    return payload


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8"))


def normalize_output(text: str) -> str:
    return text.rstrip() + "\n"


def load_env_contract_registry(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    return load_yaml(repo_root / "contracts/runtime/env_contract_registry.yaml")


def env_contract_variables(registry: dict[str, Any]) -> set[str]:
    variables: set[str] = set()
    for names in dict(registry.get("sections", {})).values():
        if not isinstance(names, list):
            continue
        variables.update(str(name) for name in names)
    return variables


def load_required_checks_policy(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    return load_yaml(repo_root / "contracts/governance/required_checks_policy.yaml")


def load_docs_render_manifest(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    return load_yaml(repo_root / "contracts/docs/docs_render_manifest.yaml")


def load_docs_nav_registry(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    return load_yaml(repo_root / "contracts/docs/docs_nav_registry.yaml")


def workflow_data(workflow_path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"workflow yaml must be mapping: {workflow_path}")
    return payload


def parse_key_value_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def parse_env_example_defaults(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def workflow_jobs(workflow_path: Path) -> list[str]:
    jobs = workflow_data(workflow_path).get("jobs", {})
    if not isinstance(jobs, dict):
        raise ValueError(f"workflow jobs must be mapping: {workflow_path}")
    return list(jobs.keys())


def workflow_has_merge_group(workflow_path: Path) -> bool:
    payload = workflow_data(workflow_path)
    on_value = payload.get("on")
    if on_value is None:
        for key, value in payload.items():
            if key is True:
                on_value = value
                break
    if isinstance(on_value, dict):
        return "merge_group" in on_value
    if isinstance(on_value, list):
        return "merge_group" in on_value
    if isinstance(on_value, str):
        return on_value == "merge_group"
    return False


def extract_web_api_routes(openapi_path: Path = OPENAPI_CONTRACT_PATH) -> list[dict[str, Any]]:
    payload = load_yaml(openapi_path)
    paths = dict(payload.get("paths", {}))
    routes: list[dict[str, Any]] = []
    for path, operations in paths.items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if str(method).upper() not in METHOD_ORDER:
                continue
            routes.append(
                {
                    "method": str(method).upper(),
                    "path": str(path),
                    "family": classify_route_family(str(path)),
                    "operation_id": str(dict(operation).get("operationId", "")),
                }
            )
    return sorted(routes, key=lambda item: (family_sort_key(item["family"]), item["path"], METHOD_ORDER[item["method"]]))


def classify_route_family(path: str) -> str:
    if path == "/healthz":
        return "Health"
    if path.startswith("/app"):
        return "UI hosting"
    if path.startswith("/api/preferences/"):
        return "Preferences"
    if path.endswith("/report") or path.endswith("/audit"):
        return "Report / audit"
    if any(token in path for token in ("/manifest",)):
        return "Manifest operations"
    if path.endswith("/events") or path.endswith("/events/stream") or path.endswith("/stream"):
        if path in {"/api/jobs/stream", "/api/jobs/history", "/api/jobs"}:
            return "Jobs / history"
        return "Job events"
    if path.endswith("/cancel") or path.endswith("/retry") or path in {"/api/jobs/analyze", "/api/jobs/apply", "/api/jobs/rollback"}:
        return "Job actions"
    if path.startswith("/api/jobs"):
        return "Jobs / history"
    return "Other"


def family_sort_key(family: str) -> int:
    order = [
        "Health",
        "Jobs / history",
        "Job events",
        "Manifest operations",
        "Job actions",
        "Report / audit",
        "Preferences",
        "UI hosting",
        "Other",
    ]
    return order.index(family) if family in order else len(order)


def route_family_summary(routes: list[dict[str, Any]]) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {}
    for route in routes:
        summary.setdefault(route["family"], []).append(route["path"])
    for family, paths in summary.items():
        summary[family] = sorted(dict.fromkeys(paths))
    return summary


def render_env_contract_reference(repo_root: Path = REPO_ROOT) -> str:
    registry = load_env_contract_registry(repo_root)
    sections = dict(registry.get("sections", {}))
    contract = sorted(env_contract_variables(registry))
    budgets = dict(registry.get("category_budgets", {}))
    lines = [
        "# Environment Contract Reference",
        "",
        "> AUTO-GENERATED from `contracts/runtime/env_contract_registry.yaml`. Do not edit manually.",
        "",
        "## Contract Snapshot",
        "",
        f"- Contract vars: `{len(contract)}`",
        "- Business env prefixes: " + ", ".join(f"`{item}`" for item in registry.get("business_env_prefixes", [])),
        "- Category budgets: " + ", ".join(f"`{prefix}{limit}`" for prefix, limit in budgets.items()),
        "",
    ]
    for section_key in ("required", "runtime_optional", "observability_context", "ci_only", "test_only"):
        names = sections.get(section_key, [])
        if not names:
            continue
        lines.extend(
            [
                f"## {SECTION_LABELS[section_key]}",
                "",
                "| Variable | Prefix |",
                "| --- | --- |",
            ]
        )
        for name in names:
            prefix = next((item for item in registry.get("business_env_prefixes", []) if str(name).startswith(str(item))), "OTHER")
            lines.append(f"| `{name}` | `{prefix}` |")
        lines.append("")
    return normalize_output("\n".join(lines))


def validate_required_checks(repo_root: Path = REPO_ROOT) -> list[str]:
    policy = load_required_checks_policy(repo_root)
    default_workflow = str(policy["workflow_file"])
    workflow_paths: dict[str, Path] = {}
    workflow_job_ids: dict[str, set[str]] = {}
    merge_group_state: dict[str, bool] = {}
    for row in policy.get("required_checks", []):
        if not isinstance(row, dict):
            continue
        workflow_file = str(row.get("workflow_file", default_workflow))
        if workflow_file in workflow_paths:
            continue
        workflow_path = repo_root / workflow_file
        workflow_paths[workflow_file] = workflow_path
        workflow_job_ids[workflow_file] = set(workflow_jobs(workflow_path))
        merge_group_state[workflow_file] = workflow_has_merge_group(workflow_path)
    errors: list[str] = []
    for row in policy.get("required_checks", []):
        job_id = str(row["job_id"])
        workflow_file = str(row.get("workflow_file", default_workflow))
        if job_id not in workflow_job_ids.get(workflow_file, set()):
            errors.append(f"policy job missing in workflow: {workflow_file} -> {job_id}")
    for workflow_file, has_merge_group in merge_group_state.items():
        if not has_merge_group:
            errors.append(f"workflow missing merge_group trigger: {workflow_file}")
    return errors


def render_required_checks_matrix(repo_root: Path = REPO_ROOT) -> str:
    policy = load_required_checks_policy(repo_root)
    default_workflow = str(policy["workflow_file"])
    workflow_job_ids: dict[str, set[str]] = {}
    for row in policy.get("required_checks", []):
        if not isinstance(row, dict):
            continue
        workflow_file = str(row.get("workflow_file", default_workflow))
        if workflow_file in workflow_job_ids:
            continue
        workflow_job_ids[workflow_file] = set(workflow_jobs(repo_root / workflow_file))
    workflow_files = sorted(workflow_job_ids)
    workflow_job_entry_count = sum(len(items) for items in workflow_job_ids.values())
    lines = [
        "# Required Checks Matrix",
        "",
        "> AUTO-GENERATED from `contracts/governance/required_checks_policy.yaml` + GitHub workflow topology. Do not edit manually.",
        "",
        "## Workflow Snapshot",
        "",
        "- Workflow files: " + ", ".join(f"`{workflow}`" for workflow in workflow_files),
        f"- Branch protection target: `{policy['branch_protection_target']}`",
        f"- Declared required checks: `{len(policy.get('required_checks', []))}`",
        f"- Workflow job entries discovered: `{workflow_job_entry_count}`",
        "- `merge_group` trigger coverage: "
        + (
            "all required-check workflows enabled"
            if all(workflow_has_merge_group(repo_root / workflow) for workflow in workflow_files)
            else "missing on one or more workflow files"
        ),
        "",
        "## Required Checks Alignment Matrix",
        "",
        "| workflow_file | job_id | purpose | blocking level | Failure-domain policy | Branch protection guidance | workflow status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in policy.get("required_checks", []):
        job_id = str(row["job_id"])
        workflow_file = str(row.get("workflow_file", default_workflow))
        status = "present" if job_id in workflow_job_ids.get(workflow_file, set()) else "missing"
        lines.append(
            "| `{workflow}` | `{job_id}` | {purpose} | `{level}` | `{failure_domain}` | {branch} | `{status}` |".format(
                workflow=workflow_file,
                job_id=job_id,
                purpose=row["purpose"],
                level=row["blocking_level"],
                failure_domain=row.get("failure_domain_policy", "unspecified"),
                branch=row["branch_protection"],
                status=status,
            )
        )
    lines.extend(
        [
            "",
            "## Failure-Domain Summary",
            "",
            "| job_id | failure_domain_policy | reason |",
            "| --- | --- | --- |",
        ]
    )
    for row in policy.get("required_checks", []):
        lines.append(
            "| `{job_id}` | `{policy}` | {reason} |".format(
                job_id=row["job_id"],
                policy=row.get("failure_domain_policy", "unspecified"),
                reason=row.get("failure_domain_reason", "None"),
            )
        )
    lines.extend(
        [
            "",
            "## Workflow Job Inventory",
            "",
            "| workflow_file | job_id | in required_checks policy |",
            "| --- | --- | --- |",
        ]
    )
    required_pairs = {
        (str(row.get("workflow_file", default_workflow)), str(row["job_id"]))
        for row in policy.get("required_checks", [])
        if isinstance(row, dict)
    }
    for workflow_file in workflow_files:
        for job_id in sorted(workflow_job_ids[workflow_file]):
            in_policy = "yes" if (workflow_file, job_id) in required_pairs else "no"
            lines.append(f"| `{workflow_file}` | `{job_id}` | `{in_policy}` |")
    lines.append("")
    return normalize_output("\n".join(lines))


def render_web_api_reference(repo_root: Path = REPO_ROOT) -> str:
    routes = extract_web_api_routes(repo_root / "contracts" / "api" / "web_api.openapi.yaml")
    summary = route_family_summary(routes)
    lines = [
        "# Web API Routes Reference",
        "",
        "> AUTO-GENERATED from `contracts/api/web_api.openapi.yaml`. Do not edit manually.",
        "",
        "## Route Family Summary",
        "",
    ]
    for family in sorted(summary, key=family_sort_key):
        lines.append("- **{family}**: {paths}".format(family=family, paths=", ".join(f"`{path}`" for path in summary[family])))
    lines.extend(
        [
            "",
            "## Endpoint Table",
            "",
            "| Method | Path | Family | Operation ID | Source |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for route in routes:
        lines.append(
            f"| `{route['method']}` | `{route['path']}` | {route['family']} | "
            f"`{route['operation_id'] or '-'}` | `contracts/api/web_api.openapi.yaml` |"
        )
    lines.extend(
        [
            "",
            "## API Naming Guardrails",
            "",
            "- `overlay` / `resolved snapshot` are internal model and file-output concepts, not stable public HTTP route names.",
            (
                "- Do not introduce alias routes such as `/api/jobs/{id}/manifest/overlay`, `/api/jobs/{id}/manifest/resolved`,"
                " `/api/views`, `/api/naming-templates`, or `/api/jobs/{id}/rollback-audit`."
            ),
            "",
        ]
    )
    return normalize_output("\n".join(lines))


def _toml_data(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _sanitize_public_runtime_value(value: str) -> str:
    sanitized = str(value)
    replacements = [
        ("~/.movi-organizer/workspaces/default/.movi", "<workspace-root>/.movi"),
        ("~/.movi-organizer/workspaces/default/data/raw", "<workspace-root>/data/raw"),
        ("~/.movi-organizer/workspaces/default/data/organized", "<workspace-root>/data/organized"),
        ("~/.movi-organizer/workspaces/default/data", "<workspace-root>/data"),
        ("~/.movi-organizer/workspaces/default", "<workspace-root>"),
        (".runtime-cache", "<repo-runtime-cache>"),
    ]
    for old, new in replacements:
        sanitized = sanitized.replace(old, new)
    return sanitized


def runtime_topology_snapshot(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    compose_data = yaml.safe_load((repo_root / "ops" / "compose" / "docker-compose.yml").read_text(encoding="utf-8"))
    governance = parse_key_value_env(repo_root / "contracts" / "governance" / "governance.defaults.env")
    runtime_layout = yaml.safe_load((repo_root / "contracts" / "runtime" / "filesystem_layout.yaml").read_text(encoding="utf-8"))
    env_defaults = parse_env_example_defaults(repo_root / ".env.example")
    pyproject = _toml_data(repo_root / "pyproject.toml")
    package = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    webui_package = json.loads((repo_root / "apps" / "webui" / "package.json").read_text(encoding="utf-8"))

    services: list[dict[str, Any]] = []
    for service_name, service in dict(compose_data.get("services", {})).items():
        service = dict(service)
        ports = service.get("ports", []) or []
        command = service.get("command", [])
        if isinstance(command, list):
            command_text = " ".join(str(item) for item in command)
        else:
            command_text = str(command)
        services.append(
            {
                "name": service_name,
                "ports": [str(item) for item in ports],
                "network_mode": str(service.get("network_mode", "")) if service.get("network_mode") else "default",
                "command": command_text,
            }
        )
    services.sort(key=lambda item: item["name"])

    runtime_paths = {
        key: value
        for key, value in governance.items()
        if key.startswith("GOVERNANCE_RUNTIME_") or key in {"GOVERNANCE_PERSISTENT_ARTIFACTS_DIR", "GOVERNANCE_WEBUI_LOCK_HASH_FILE"}
    }

    env_defaults_subset = {
        key: env_defaults[key]
        for key in (
            "GEMINI_MODEL",
            "MOVI_WEB_API_HOST",
            "MOVI_WEB_API_PORT",
            "MOVI_WEBUI_HOST",
            "MOVI_WEBUI_PORT",
            "MOVI_COMPOSE_SERVICE",
            "MOVI_CI_IMAGE",
        )
        if key in env_defaults
    }

    project_scripts = dict(pyproject.get("project", {}).get("scripts", {}))
    package_smoke = dict(pyproject.get("tool", {}).get("movi_organizer", {}).get("package_smoke", {}))
    npm_scripts = dict(package.get("scripts", {}))
    docker_runtime = dict(runtime_layout.get("docker_runtime", {})) if isinstance(runtime_layout, dict) else {}
    return {
        "services": services,
        "runtime_paths": runtime_paths,
        "env_defaults": env_defaults_subset,
        "cleanup_rails": [
            {
                "name": "repo-local residue",
                "commands": ["bash tooling/cleanup/prune_repo_runtime.sh"],
                "note": "Trim checkout-local runtime noise under <repo-runtime-cache>.",
            },
            {
                "name": "machine cache",
                "commands": [
                    "bash tooling/cleanup/prune_machine_cache.sh --safe",
                    "bash tooling/cleanup/prune_machine_cache.sh --rebuildable",
                    "bash tooling/cleanup/prune_machine_cache.sh --aggressive-host",
                ],
                "note": "Governed host-side cache lane; host venv is fallback-only in the container-first model.",
            },
            {
                "name": "docker runtime",
                "commands": [
                    "bash tooling/cleanup/prune_docker_runtime.sh --dry-run",
                    "bash tooling/cleanup/prune_docker_runtime.sh --rebuildable",
                    "bash tooling/cleanup/prune_docker_runtime.sh --aggressive",
                ],
                "note": "Canonical runtime rail backed by the current Docker image, named volumes, and repo-related build cache.",
            },
            {
                "name": "destructive workspace reset",
                "commands": ["bash tooling/runtime/runtime_reset.sh --confirm-workspace-reset"],
                "note": "Clears workspace .movi state; not a routine cache cleanup command.",
            },
        ],
        "docker_runtime": docker_runtime,
        "python_entrypoints": project_scripts,
        "package_smoke_entrypoints": list(package_smoke.get("required_entrypoints", [])),
        "workspace_scripts": {key: npm_scripts[key] for key in ("dev:stack", "dev:stack:compose", "build") if key in npm_scripts},
        "webui_scripts": {
            key: webui_package.get("scripts", {}).get(key)
            for key in ("dev", "build", "test", "lint")
            if key in webui_package.get("scripts", {})
        },
    }


def render_runtime_topology_reference(repo_root: Path = REPO_ROOT) -> str:
    snapshot = runtime_topology_snapshot(repo_root)
    lines = [
        "# Runtime Topology Reference",
        "",
        (
            "> AUTO-GENERATED from `ops/compose/docker-compose.yml`, `contracts/governance/governance.defaults.env`, "
            "`contracts/runtime/filesystem_layout.yaml`, `pyproject.toml`, `package.json`, `.env.example`. Do not edit manually."
        ),
        (
            "> Navigation note: this page is the shared runtime-topology reference for README / "
            "docs/usage / docs/architecture, and it is the canonical anchor for executable gates "
            "and default entry facts."
        ),
        "> Public docs use semantic placeholders to avoid over-publishing local workspace layouts.",
        (
            "> `<workspace-root>` means a user-chosen persistent workspace directory; "
            "`<repo-runtime-cache>` means the repo-local runtime cache directory."
        ),
        "",
        "## Compose Services",
        "",
        "| service | ports | network_mode | command |",
        "| --- | --- | --- | --- |",
    ]
    for service in snapshot["services"]:
        ports = ", ".join(f"`{item}`" for item in service["ports"]) if service["ports"] else "—"
        command = f"`{service['command']}`" if service["command"] else "—"
        lines.append(f"| `{service['name']}` | {ports} | `{service['network_mode']}` | {command} |")
    lines.extend(["", "## Runtime Paths", "", "| key | value |", "| --- | --- |"])
    for key, value in sorted(snapshot["runtime_paths"].items()):
        lines.append(f"| `{key}` | `{_sanitize_public_runtime_value(value)}` |")
    lines.extend(["", "## Default Runtime Knobs", "", "| key | default |", "| --- | --- |"])
    for key, value in snapshot["env_defaults"].items():
        rendered = _sanitize_public_runtime_value(value) if value else "(empty)"
        lines.append(f"| `{key}` | `{rendered}` |")
    lines.extend(["", "## Cleanup Rails", ""])
    for rail in snapshot["cleanup_rails"]:
        lines.append(f"- **{rail['name']}**: " + ", ".join(f"`{command}`" for command in rail["commands"]))
        lines.append(f"  {rail['note']}")
    docker_runtime = snapshot.get("docker_runtime", {})
    if docker_runtime:
        protected = ", ".join(f"`{item}`" for item in docker_runtime.get("protected_volumes", []))
        optional = ", ".join(f"`{item}`" for item in docker_runtime.get("optional_volumes", []))
        lines.extend(
            [
                "",
                "### Container-First Defaults",
                "",
                f"- Canonical Docker image: `{docker_runtime.get('canonical_image', 'movi-ci:local')}`",
                f"- Protected Docker volumes: {protected or 'None'}",
                f"- Optional Docker volumes: {optional or 'None'}",
                (
                    "- Shared-related surface: `"
                    + (", ".join(str(item) for item in docker_runtime.get("shared_related_surface", [])) or "docker build cache")
                    + "`"
                ),
            ]
        )
    lines.extend(["", "## Entrypoints", "", "### Python entrypoints", ""])
    for key, value in snapshot["python_entrypoints"].items():
        lines.append(f"- `{key}` -> `{value}`")
    lines.extend(["", "### Package smoke required entrypoints", ""])
    for name in snapshot["package_smoke_entrypoints"]:
        lines.append(f"- `{name}`")
    lines.extend(["", "### Workspace scripts", ""])
    for key, value in snapshot["workspace_scripts"].items():
        lines.append(f"- `{key}` -> `{value}`")
    lines.extend(["", "### WebUI scripts", ""])
    for key, value in snapshot["webui_scripts"].items():
        lines.append(f"- `{key}` -> `{value}`")
    lines.append("")
    return normalize_output("\n".join(lines))


def _reference_link_for(target_path: str) -> str:
    mapping = {
        "README.md": "docs/reference/web_api_routes.generated.md",
        "docs/usage.md": "docs/reference/web_api_routes.generated.md",
        "docs/architecture.md": "reference/web_api_routes.generated.md",
        "apps/webui/README.md": "../docs/reference/web_api_routes.generated.md",
    }
    if target_path in mapping:
        return mapping[target_path]
    return Path(os.path.relpath("docs/reference/web_api_routes.generated.md", start=Path(target_path).parent or Path("."))).as_posix()


def render_web_api_summary_block(output_path: str, repo_root: Path = REPO_ROOT) -> str:
    routes = extract_web_api_routes(repo_root / "contracts" / "api" / "web_api.openapi.yaml")
    summary = route_family_summary(routes)
    lines = [
        "> Auto-generated: current Web API facts come from `contracts/api/web_api.openapi.yaml`; the full method/path list lives in "
        f"[generated reference]({_reference_link_for(output_path)}).",
        "",
    ]
    for family in ("Jobs / history", "Job events", "Manifest operations", "Job actions", "Report / audit", "Preferences"):
        paths = summary.get(family)
        if not paths:
            continue
        lines.append(f"- **{family}**: " + ", ".join(f"`{path}`" for path in paths))
    lines.append("- `overlay` / `resolved snapshot` are internal model and file-output concepts, not stable public HTTP routes.")
    return "\n".join(lines)


def _runtime_reference_link_for(target_path: str) -> str:
    mapping = {
        "README.md": "docs/reference/runtime_topology.generated.md",
        "docs/usage.md": "docs/reference/runtime_topology.generated.md",
        "docs/architecture.md": "reference/runtime_topology.generated.md",
    }
    if target_path in mapping:
        return mapping[target_path]
    start = Path(target_path).parent or Path(".")
    return Path(os.path.relpath("docs/reference/runtime_topology.generated.md", start=start)).as_posix()


def _required_checks_link_for(target_path: str) -> str:
    mapping = {
        "README.md": "docs/required_checks_matrix.md",
        "docs/usage.md": "docs/required_checks_matrix.md",
    }
    return mapping[target_path]


def _runner_contract_link_for(target_path: str) -> str:
    mapping = {
        "README.md": "docs/runner_contract.md",
        "docs/usage.md": "docs/runner_contract.md",
    }
    return mapping[target_path]


def _workflow_link_for(target_path: str, workflow_name: str) -> str:
    prefix = "" if target_path == "README.md" else "../"
    return f"{prefix}.github/workflows/{workflow_name}"


def render_runtime_topology_summary_block(output_path: str, repo_root: Path = REPO_ROOT) -> str:
    snapshot = runtime_topology_snapshot(repo_root)
    services = ", ".join(f"`{service['name']}`" for service in snapshot["services"])
    api_port = snapshot["env_defaults"].get("MOVI_WEB_API_PORT", "18080")
    webui_port = snapshot["env_defaults"].get("MOVI_WEBUI_PORT", "5173")
    lines = [
        "> Auto-generated: runtime services, default ports, runtime paths, and entrypoint facts live in "
        f"[generated runtime topology]({_runtime_reference_link_for(output_path)}).",
        "",
        f"- **Compose services**: {services}",
        f"- **Web API bind**: `loopback:{api_port}`",
        f"- **WebUI bind**: `loopback:{webui_port}`",
        "- **Persistent workspace docs alias**: `<workspace-root>`",
        "- **Repo-local cache docs alias**: `<repo-runtime-cache>`",
    ]
    return "\n".join(lines)


def render_ci_governance_summary_block(output_path: str, repo_root: Path = REPO_ROOT) -> str:
    policy = load_required_checks_policy(repo_root)
    dual_lane_jobs = [
        f"`{row['job_id']}`"
        for row in policy.get("required_checks", [])
        if row.get("failure_domain_policy") == "hosted-primary-plus-shared-pool-fallback"
    ]
    shared_pool_only_jobs = [
        f"`{row['job_id']}`" for row in policy.get("required_checks", []) if row.get("failure_domain_policy") == "shared-pool-only-accepted"
    ]
    package = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    has_local_ci = "ci:local" in dict(package.get("scripts", {}))
    lines = [
        "> Auto-generated: CI truth-chain, failure-domain policy, navigation entrypoints, and executable gate facts come from "
        f"[required checks matrix]({_required_checks_link_for(output_path)}), "
        f"[runner contract]({_runner_contract_link_for(output_path)}), "
        f"and [ci.yml]({_workflow_link_for(output_path, 'ci.yml')}).",
        "",
        (
            "- **Canonical truth path**: `build-ci-image -> change-detection -> "
            "{webui-build-test, quality-gate-full} -> functional-gate -> test`"
        ),
        "- **Canonical gate**: `quality-gate-full`",
        (
            "- **Supplemental gates**: `webui-build-test` (frontend correctness), "
            "`functional-gate` (critical smoke), `test` (Python version parity)"
        ),
        "- **Dual failure-domain required jobs**: " + (", ".join(dual_lane_jobs) if dual_lane_jobs else "None"),
        "- **Shared-pool-only required jobs**: " + (", ".join(shared_pool_only_jobs) if shared_pool_only_jobs else "None"),
        (
            "- **Side workflows**: `pre-commit` bootstraps directly on hosted runners, while "
            "`live-integration` and `mutation-manual` reuse `reusable-build-runtime-image.yml`; "
            "runtime image build keeps provenance artifact wiring when the platform supports attestations."
        ),
        "- **Drift / evidence surfaces**: `nightly-drift-audit.yml`, `collect_ci_run_metrics.py`, `generate_ci_evidence_bundle.py`.",
    ]
    if has_local_ci:
        lines.append(
            "- **Local auxiliary evidence**: `npm run ci:local` writes repo-local CI metrics, "
            "a repo-local evidence bundle, and governed upstream receipts under the repo-local "
            "runtime cache directory; these are local derived reports, not Branch Protection truth. Read `truth.truth_class`, "
            "`truth.remote_traceability`, and `truth.authoritative_terminal_receipt` before "
            "treating the bundle as anything stronger. Older pass receipts remain historical "
            "audit evidence only; current closeout wording must follow the latest canonical "
            "terminal receipt."
        )
    lines.append(
        "- **Developer fallback**: use `bash tooling/gates/pre_push_gate.sh` "
        "(`standard/strict/full`) for fast local feedback before remote CI."
    )
    return "\n".join(lines)


def release_identity_snapshot(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    if not isinstance(project, dict):
        raise ValueError("pyproject [project] must be mapping")
    package_version = str(project.get("version", "")).strip()
    derived_tag = f"v{package_version}" if package_version else ""
    return {
        "package_version": package_version,
        "tag_name": derived_tag,
        "boundary_status": "requires_local_release_evidence",
        "publish_mode": "",
        "published_at": "",
        "evidence_mode": "tracked_only",
    }


def render_release_identity_summary_block(output_path: str, repo_root: Path = REPO_ROOT) -> str:
    snapshot = release_identity_snapshot(repo_root)
    lines = [
        (
            "> Auto-generated: the current source package version comes from `pyproject.toml`. "
            "`current-head release` boundaries depend on local/CI runtime evidence, and a clean checkout does not "
            "carry a repo-local release evidence summary by default."
        ),
        "",
        f"- **Current source package version**: `{snapshot['package_version']}`",
        f"- **Current current-head release tag**: `{snapshot['tag_name']}`",
        f"- **Current current-head release boundary**: `{snapshot['boundary_status']}`",
        "- **Current release publish status**: `unknown in clean checkout`",
        (
            "- **How to read this**: run `npm run release:truth`, then read "
            "`current_head_release_truth.status` before making current-head release claims."
        ),
        "- **Verified published closure**: only `published_release_verified` can be described as a verified published closure.",
    ]
    return "\n".join(lines)


def _relative_doc_link(target_path: str, destination: str) -> str:
    mapping = {
        ("README.md", "docs/reference/governance_truth.generated.md"): "docs/reference/governance_truth.generated.md",
        ("README.md", "docs/required_checks_matrix.md"): "docs/required_checks_matrix.md",
        ("README.md", "docs/runner_contract.md"): "docs/runner_contract.md",
        ("README.md", "docs/open_source_runbook.md"): "docs/open_source_runbook.md",
        ("docs/usage.md", "docs/reference/governance_truth.generated.md"): "docs/reference/governance_truth.generated.md",
        ("docs/usage.md", "docs/required_checks_matrix.md"): "docs/required_checks_matrix.md",
        ("docs/usage.md", "docs/runner_contract.md"): "docs/runner_contract.md",
        ("docs/usage.md", "docs/open_source_runbook.md"): "docs/open_source_runbook.md",
        ("docs/architecture.md", "docs/reference/governance_truth.generated.md"): "reference/governance_truth.generated.md",
        ("docs/architecture.md", "docs/required_checks_matrix.md"): "required_checks_matrix.md",
        ("docs/architecture.md", "docs/runner_contract.md"): "runner_contract.md",
        ("docs/architecture.md", "docs/open_source_runbook.md"): "open_source_runbook.md",
        ("docs/runner_contract.md", "docs/reference/governance_truth.generated.md"): "reference/governance_truth.generated.md",
        ("docs/runner_contract.md", "docs/required_checks_matrix.md"): "required_checks_matrix.md",
        ("docs/runner_contract.md", "docs/open_source_runbook.md"): "open_source_runbook.md",
        ("docs/open_source_runbook.md", "docs/reference/governance_truth.generated.md"): "reference/governance_truth.generated.md",
        ("docs/open_source_runbook.md", "docs/required_checks_matrix.md"): "required_checks_matrix.md",
        ("docs/open_source_runbook.md", "docs/runner_contract.md"): "runner_contract.md",
    }
    key = (target_path, destination)
    if key in mapping:
        return mapping[key]
    start = Path(target_path).parent or Path(".")
    return Path(os.path.relpath(destination, start=start)).as_posix()


def _governance_reference_link_for(target_path: str) -> str:
    return _relative_doc_link(target_path, "docs/reference/governance_truth.generated.md")


def _extract_runner_bootstrap_contract(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    workflow = workflow_data(repo_root / ".github" / "workflows" / "ci.yml")
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        raise ValueError("ci workflow jobs must be mapping")
    bootstrap_job = "ci-bootstrap" if "ci-bootstrap" in jobs else "ci-bootstrap"
    manual_only_workflows: list[str] = []
    sensitive_environments: list[str] = []
    workflow_paths = [
        ".github/workflows/ci.yml",
        ".github/workflows/pre-commit.yml",
        ".github/workflows/live-integration.yml",
        ".github/workflows/mutation-manual.yml",
    ]
    for rel_path in workflow_paths:
        payload = workflow_data(repo_root / rel_path)
        trigger_block = payload.get("on", {})
        trigger_names: set[str] = set()
        if isinstance(trigger_block, dict):
            trigger_names = {str(name).strip() for name in trigger_block}
        elif isinstance(trigger_block, list):
            trigger_names = {str(name).strip() for name in trigger_block}
        elif isinstance(trigger_block, str):
            trigger_names = {trigger_block.strip()}
        if (
            "workflow_dispatch" in trigger_names
            and "pull_request" not in trigger_names
            and "push" not in trigger_names
            and "merge_group" not in trigger_names
        ):
            manual_only_workflows.append(Path(rel_path).name)
        job_defs = payload.get("jobs", {})
        if not isinstance(job_defs, dict):
            continue
        for job in job_defs.values():
            if not isinstance(job, dict):
                continue
            environment = job.get("environment")
            if isinstance(environment, str) and environment.strip():
                sensitive_environments.append(environment.strip())
    return {
        "bootstrap_job": bootstrap_job,
        "workflow_file": ".github/workflows/ci.yml",
        "runner_model": "github-hosted-only",
        "manual_only_workflows": sorted(dict.fromkeys(manual_only_workflows)),
        "sensitive_environments": sorted(dict.fromkeys(sensitive_environments)),
    }


def governance_truth_snapshot(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    done_signal = load_yaml(repo_root / "contracts" / "governance" / "done_signal_policy.yaml")
    public_readiness = load_yaml(repo_root / "contracts" / "governance" / "public_readiness_policy.yaml")
    required_checks = load_required_checks_policy(repo_root)
    required_rows = [row for row in required_checks.get("required_checks", []) if isinstance(row, dict)]
    dual_lane = [str(row["job_id"]) for row in required_rows if row.get("failure_domain_policy") == "hosted-primary-plus-hosted-retry"]
    shared_pool_only = [str(row["job_id"]) for row in required_rows if row.get("failure_domain_policy") == "shared-pool-only-accepted"]
    runner_bootstrap = _extract_runner_bootstrap_contract(repo_root)
    runbook_snippets = [str(item) for item in public_readiness.get("required_runbook_snippets", []) if str(item)]
    return {
        "done_signal": {
            "delivery_gate": str(done_signal.get("canonical_delivery_gate", "")),
            "governance_gate": str(done_signal.get("governance_scorecard_gate", "")),
            "claim_surface_count": len(done_signal.get("claim_surfaces", [])),
        },
        "required_checks": {
            "workflow_file": str(required_checks.get("workflow_file", "")),
            "workflow_files": sorted({str(row.get("workflow_file", required_checks.get("workflow_file", ""))) for row in required_rows}),
            "branch_target": str(required_checks.get("branch_protection_target", "")),
            "required_count": len(required_rows),
            "dual_lane_jobs": dual_lane,
            "shared_pool_only_jobs": shared_pool_only,
        },
        "public_readiness": {
            "repo_gate": next((item for item in runbook_snippets if item.endswith("public_readiness_gate.sh repo")), ""),
            "release_gate": next((item for item in runbook_snippets if item.endswith("public_readiness_gate.sh release")), ""),
            "platform_alignment_gate": next((item for item in runbook_snippets if item.endswith("platform_alignment_gate.sh")), ""),
            "required_repo_surface_count": len(public_readiness.get("required_repo_surface_files", [])),
            "required_package_script_count": len(public_readiness.get("required_package_scripts", [])),
            "release_mode": {
                "require_tracked_files": bool(dict(public_readiness.get("release_mode", {})).get("require_tracked_files", False)),
                "require_public_repo": bool(dict(public_readiness.get("release_mode", {})).get("require_public_repo", False)),
                "require_pvr": bool(dict(public_readiness.get("release_mode", {})).get("require_pvr", False)),
                "require_branch_protection": bool(dict(public_readiness.get("release_mode", {})).get("require_branch_protection", False)),
            },
        },
        "runner_bootstrap": runner_bootstrap,
    }


def render_governance_truth_reference(repo_root: Path = REPO_ROOT) -> str:
    snapshot = governance_truth_snapshot(repo_root)
    done_signal = snapshot["done_signal"]
    required_checks = snapshot["required_checks"]
    public_readiness = snapshot["public_readiness"]
    runner_bootstrap = snapshot["runner_bootstrap"]
    release_flags = public_readiness["release_mode"]
    lines = [
        "# Governance Truth Reference",
        "",
        (
            "> AUTO-GENERATED from `contracts/governance/done_signal_policy.yaml`, "
            "`contracts/governance/public_readiness_policy.yaml`, "
            "`contracts/governance/required_checks_policy.yaml`, and GitHub workflow topology. "
            "Do not edit manually."
        ),
        (
            "> Navigation note: this page carries the high-drift done-signal, required-checks, "
            "runner-capacity, and platform-alignment facts; longer human docs should keep only why/rule/tradeoff/runbook explanations."
        ),
        "",
        "## Done Signal Truth",
        "",
        f"- **Delivery-complete gate**: `{done_signal['delivery_gate']}`",
        f"- **Repo governance scorecard**: `{done_signal['governance_gate']}`",
        f"- **Claim surfaces guarded by policy**: `{done_signal['claim_surface_count']}`",
        "",
        "## Required Checks Snapshot",
        "",
        "- **Workflow files**: " + ", ".join(f"`{workflow}`" for workflow in required_checks["workflow_files"]),
        f"- **Branch protection target**: `{required_checks['branch_target']}`",
        f"- **Required checks count**: `{required_checks['required_count']}`",
        "- **Dual hosted-lane required jobs**: "
        + (", ".join(f"`{job}`" for job in required_checks["dual_lane_jobs"]) if required_checks["dual_lane_jobs"] else "None"),
        "- **Legacy shared-pool-only required jobs**: "
        + (
            ", ".join(f"`{job}`" for job in required_checks["shared_pool_only_jobs"])
            if required_checks["shared_pool_only_jobs"]
            else "None"
        ),
        "",
        "## Hosted CI Contract",
        "",
        f"- **Bootstrap workflow/job**: `{runner_bootstrap['workflow_file']} -> {runner_bootstrap['bootstrap_job']}`",
        f"- **Runner model**: `{runner_bootstrap['runner_model']}`",
        "- **Manual-only workflows**: "
        + (
            ", ".join(f"`{name}`" for name in runner_bootstrap["manual_only_workflows"])
            if runner_bootstrap["manual_only_workflows"]
            else "None"
        ),
        "- **Protected sensitive environments**: "
        + (
            ", ".join(f"`{name}`" for name in runner_bootstrap["sensitive_environments"])
            if runner_bootstrap["sensitive_environments"]
            else "None"
        ),
        "",
        "## Public Readiness / Platform Alignment",
        "",
        f"- **Repo public readiness gate**: `{public_readiness['repo_gate']}`",
        f"- **Release public readiness gate**: `{public_readiness['release_gate']}`",
        f"- **Platform alignment gate**: `{public_readiness['platform_alignment_gate']}`",
        f"- **Required repo surface files**: `{public_readiness['required_repo_surface_count']}`",
        f"- **Required package scripts**: `{public_readiness['required_package_script_count']}`",
        "- **Release-mode requires tracked public files**: `{}`".format("yes" if release_flags["require_tracked_files"] else "no"),
        "- **Release-mode requires public repo**: `{}`".format("yes" if release_flags["require_public_repo"] else "no"),
        "- **Release-mode requires PVR**: `{}`".format("yes" if release_flags["require_pvr"] else "no"),
        "- **Release-mode requires branch protection**: `{}`".format("yes" if release_flags["require_branch_protection"] else "no"),
        "",
    ]
    return normalize_output("\n".join(lines))


def render_governance_truth_summary_block(output_path: str, repo_root: Path = REPO_ROOT) -> str:
    snapshot = governance_truth_snapshot(repo_root)
    done_signal = snapshot["done_signal"]
    public_readiness = snapshot["public_readiness"]
    runner_bootstrap = snapshot["runner_bootstrap"]
    lines = [
        "> Auto-generated: delivery-complete truth, governance scorecard truth, hosted CI facts, and platform-alignment facts live in "
        f"[generated governance reference]({_governance_reference_link_for(output_path)}), "
        f"[required checks matrix]({_relative_doc_link(output_path, 'docs/required_checks_matrix.md')}), "
        f"and [runner contract]({_relative_doc_link(output_path, 'docs/runner_contract.md')}).",
        "",
        f"- **Delivery-complete gate**: `{done_signal['delivery_gate']}`",
        f"- **Repo governance scorecard**: `{done_signal['governance_gate']}`",
        f"- **Platform alignment gate**: `{public_readiness['platform_alignment_gate']}`",
        f"- **Hosted CI model**: `{runner_bootstrap['runner_model']}`",
        "- **Protected sensitive environments**: "
        + (
            ", ".join(f"`{name}`" for name in runner_bootstrap["sensitive_environments"])
            if runner_bootstrap["sensitive_environments"]
            else "None"
        ),
    ]
    return "\n".join(lines)


def render_open_source_platform_truth_block(output_path: str, repo_root: Path = REPO_ROOT) -> str:
    snapshot = governance_truth_snapshot(repo_root)
    public_readiness = snapshot["public_readiness"]
    release_flags = public_readiness["release_mode"]
    lines = [
        "> Auto-generated: public-surface and platform-state policy facts live in "
        f"[generated governance reference]({_governance_reference_link_for(output_path)}), "
        f"and [required checks matrix]({_relative_doc_link(output_path, 'docs/required_checks_matrix.md')}).",
        "",
        f"- **Repo public readiness gate**: `{public_readiness['repo_gate']}`",
        f"- **Release public readiness gate**: `{public_readiness['release_gate']}`",
        f"- **Platform alignment gate**: `{public_readiness['platform_alignment_gate']}`",
        (
            "- **Release-mode policy**: tracked public files=`{tracked}` / public repo=`{public}` "
            "/ PVR=`{pvr}` / branch protection=`{branch}`"
        ).format(
            tracked="yes" if release_flags["require_tracked_files"] else "no",
            public="yes" if release_flags["require_public_repo"] else "no",
            pvr="yes" if release_flags["require_pvr"] else "no",
            branch="yes" if release_flags["require_branch_protection"] else "no",
        ),
    ]
    return "\n".join(lines)


def render_runner_contract_summary_block(output_path: str, repo_root: Path = REPO_ROOT) -> str:
    snapshot = governance_truth_snapshot(repo_root)
    required_checks = snapshot["required_checks"]
    runner_bootstrap = snapshot["runner_bootstrap"]
    lines = [
        "> Auto-generated: hosted CI mode, protected environments, and failure-domain facts live in "
        f"[generated governance reference]({_governance_reference_link_for(output_path)}), "
        f"and [required checks matrix]({_relative_doc_link(output_path, 'docs/required_checks_matrix.md')}).",
        "",
        f"- **Bootstrap workflow/job**: `{runner_bootstrap['workflow_file']} -> {runner_bootstrap['bootstrap_job']}`",
        f"- **Runner model**: `{runner_bootstrap['runner_model']}`",
        "- **Manual-only workflows**: "
        + (
            ", ".join(f"`{name}`" for name in runner_bootstrap["manual_only_workflows"])
            if runner_bootstrap["manual_only_workflows"]
            else "None"
        ),
        "- **Protected sensitive environments**: "
        + (
            ", ".join(f"`{name}`" for name in runner_bootstrap["sensitive_environments"])
            if runner_bootstrap["sensitive_environments"]
            else "None"
        ),
        (
            "- **Failure-domain policy count**: "
            f"dual-lane `{len(required_checks['dual_lane_jobs'])}` / "
            f"legacy-shared-pool-only `{len(required_checks['shared_pool_only_jobs'])}`"
        ),
    ]
    return "\n".join(lines)


def apply_generated_block(original_text: str, block_id: str, block_body: str) -> str:
    replacement = f"<!-- BEGIN GENERATED: {block_id} -->\n{block_body.rstrip()}\n<!-- END GENERATED: {block_id} -->"
    match_count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal match_count
        if match.group("block_id") == block_id:
            match_count += 1
            return replacement
        return match.group(0)

    updated = GENERATED_BLOCK_PATTERN.sub(_replace, original_text)
    if match_count != 1:
        raise ValueError(f"generated block not found or duplicated: {block_id}")
    return normalize_output(updated)


def source_hashes(repo_root: Path, source_paths: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for rel in source_paths:
        path = repo_root / rel
        result[rel] = sha256_file(path)
    return result


def build_render_outputs(repo_root: Path = REPO_ROOT) -> tuple[dict[str, str], dict[str, Any]]:
    manifest = load_docs_render_manifest(repo_root)
    outputs: dict[str, str] = {}
    state_entries: list[dict[str, Any]] = []
    output_indices_by_path: dict[str, list[int]] = {}
    for item in manifest.get("renders", []):
        render_id = str(item["id"])
        kind = str(item["kind"])
        renderer = str(item["renderer"])
        source_paths = [str(path) for path in item.get("source_paths", [])]
        output_path = str(item["output_path"])
        if renderer == "env-contract-reference":
            rendered = render_env_contract_reference(repo_root)
        elif renderer == "required-checks-matrix":
            rendered = render_required_checks_matrix(repo_root)
        elif renderer == "web-api-reference":
            rendered = render_web_api_reference(repo_root)
        elif renderer == "runtime-topology-reference":
            rendered = render_runtime_topology_reference(repo_root)
        elif renderer == "governance-truth-reference":
            rendered = render_governance_truth_reference(repo_root)
        elif renderer in {
            "readme-web-api-summary",
            "script-readme-web-api-summary",
            "architecture-web-api-summary",
            "webui-api-contract",
        }:
            target_text = outputs.get(output_path)
            if target_text is None:
                target_text = (repo_root / output_path).read_text(encoding="utf-8")
            rendered = apply_generated_block(
                target_text,
                str(item["block_id"]),
                render_web_api_summary_block(output_path, repo_root),
            )
        elif renderer in {
            "root-runtime-topology-summary",
            "script-readme-runtime-topology-summary",
            "architecture-runtime-topology-summary",
        }:
            target_text = outputs.get(output_path)
            if target_text is None:
                target_text = (repo_root / output_path).read_text(encoding="utf-8")
            rendered = apply_generated_block(
                target_text,
                str(item["block_id"]),
                render_runtime_topology_summary_block(output_path, repo_root),
            )
        elif renderer in {
            "root-ci-governance-summary",
            "script-readme-ci-governance-summary",
        }:
            target_text = outputs.get(output_path)
            if target_text is None:
                target_text = (repo_root / output_path).read_text(encoding="utf-8")
            rendered = apply_generated_block(
                target_text,
                str(item["block_id"]),
                render_ci_governance_summary_block(output_path, repo_root),
            )
        elif renderer in {
            "root-release-identity-summary",
            "script-readme-release-identity-summary",
        }:
            target_text = outputs.get(output_path)
            if target_text is None:
                target_text = (repo_root / output_path).read_text(encoding="utf-8")
            rendered = apply_generated_block(
                target_text,
                str(item["block_id"]),
                render_release_identity_summary_block(output_path, repo_root),
            )
        elif renderer in {
            "script-readme-governance-truth-summary",
            "architecture-governance-truth-summary",
        }:
            target_text = outputs.get(output_path)
            if target_text is None:
                target_text = (repo_root / output_path).read_text(encoding="utf-8")
            rendered = apply_generated_block(
                target_text,
                str(item["block_id"]),
                render_governance_truth_summary_block(output_path, repo_root),
            )
        elif renderer == "open-source-platform-truth-summary":
            target_text = outputs.get(output_path)
            if target_text is None:
                target_text = (repo_root / output_path).read_text(encoding="utf-8")
            rendered = apply_generated_block(
                target_text,
                str(item["block_id"]),
                render_open_source_platform_truth_block(output_path, repo_root),
            )
        elif renderer == "runner-contract-governance-truth-summary":
            target_text = outputs.get(output_path)
            if target_text is None:
                target_text = (repo_root / output_path).read_text(encoding="utf-8")
            rendered = apply_generated_block(
                target_text,
                str(item["block_id"]),
                render_runner_contract_summary_block(output_path, repo_root),
            )
        else:
            raise ValueError(f"unknown renderer: {renderer}")
        outputs[output_path] = normalize_output(rendered)
        state_entries.append(
            {
                "id": render_id,
                "kind": kind,
                "renderer": renderer,
                "output_path": output_path,
                "block_id": item.get("block_id"),
                "source_hashes": source_hashes(repo_root, source_paths),
                "output_hash": sha256_text(outputs[output_path]),
            }
        )
        output_indices_by_path.setdefault(output_path, []).append(len(state_entries) - 1)

    # Multiple generated blocks can target the same file. The final render state
    # must record the hash of the final output, not the intermediate hash from
    # the first block applied to that file.
    for output_path, indices in output_indices_by_path.items():
        final_hash = sha256_text(outputs[output_path])
        for index in indices:
            state_entries[index]["output_hash"] = final_hash

    state = {
        "generator": "tooling/docs/render_docs.py@1",
        "renders": state_entries,
    }
    render_state_path = str(manifest["render_state_path"])
    outputs[render_state_path] = normalize_output(json.dumps(state, indent=2))
    return outputs, state
