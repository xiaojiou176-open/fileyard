#!/usr/bin/env python3
"""Monitor runtime/cache retention surfaces and warn when thresholds drift."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPO_CLEANUP_CMD = "bash tooling/cleanup/prune_repo_runtime.sh"
MACHINE_SAFE_CLEANUP_CMD = "bash tooling/cleanup/prune_machine_cache.sh --safe"
MACHINE_REBUILDABLE_CLEANUP_CMD = "bash tooling/cleanup/prune_machine_cache.sh --rebuildable"
MACHINE_AGGRESSIVE_CLEANUP_CMD = "bash tooling/cleanup/prune_machine_cache.sh --aggressive-host"
WORKSPACE_CLEANUP_CMD = "bash tooling/cleanup/prune_workspace_runtime.sh --dry-run"
DOCKER_AUDIT_CMD = "bash tooling/cleanup/prune_docker_runtime.sh --dry-run"
DOCKER_REBUILDABLE_CMD = "bash tooling/cleanup/prune_docker_runtime.sh --rebuildable"
DOCKER_AGGRESSIVE_CMD = "bash tooling/cleanup/prune_docker_runtime.sh --aggressive"


def get_dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total_bytes = 0
    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            total_bytes += file_path.stat().st_size
        except FileNotFoundError:
            continue
    return total_bytes / (1024 * 1024)


def load_contract(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"invalid yaml: {path}")
    return data


def resolve_path(repo_root: Path, raw_path: str, env_name: str | None = None) -> Path:
    if env_name and os.environ.get(env_name, "").strip():
        return Path(os.environ[env_name]).expanduser()
    if raw_path == "~":
        return Path.home()
    if raw_path.startswith("~/"):
        return (Path.home() / raw_path[2:]).expanduser()
    path = Path(raw_path)
    if path.is_absolute():
        return path.expanduser()
    return (repo_root / path).resolve()


def iter_direct_children(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(path.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)


def extract_status_tokens(obj: object, out: set[str]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in {"status", "overall_status", "phase_label"} and isinstance(value, str):
                out.add(value.strip().lower())
            extract_status_tokens(value, out)
    elif isinstance(obj, list):
        for item in obj:
            extract_status_tokens(item, out)


def path_is_failure_like(path: Path) -> bool:
    failure_tokens = {"fail", "failed", "error", "cancelled", "canceled"}
    json_files: list[Path] = []
    for pattern in ("job.json", "summary.json"):
        json_files.extend(path.rglob(pattern))
    json_files.extend(p for p in path.rglob("*.json") if p.name not in {"job.json", "summary.json"})
    for candidate in json_files[:20]:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        tokens: set[str] = set()
        extract_status_tokens(payload, tokens)
        if tokens & failure_tokens:
            return True
    return False


def bucket_entry(
    *,
    path_or_object: str,
    size_mb: float,
    ownership_class: str,
    reclaim_class: str,
    protected: bool,
    exists_or_present: bool,
    status: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "path_or_object": path_or_object,
        "size_mb": round(size_mb, 2),
        "ownership_class": ownership_class,
        "reclaim_class": reclaim_class,
        "protected": protected,
        "exists_or_present": exists_or_present,
        "status": status,
        # Compatibility aliases for older consumers/tests.
        "path": path_or_object,
        "exists": exists_or_present,
    }
    if extra:
        payload.update(extra)
    return payload


def status_for_threshold(size_mb: float, warn_mb: float, error_mb: float) -> str:
    if size_mb >= error_mb:
        return "over_error"
    if size_mb >= warn_mb:
        return "over_warn"
    return "within_policy"


def repo_entry_classification(name: str) -> tuple[str, str, bool]:
    if name in {".runtime-cache/logs/quality-gate", ".runtime-cache/logs/scancode", ".runtime-cache/ci"}:
        return ("repo_exclusive", "protected_receipt_lane", False)
    if name in {
        ".runtime-cache/build/tooling/mypy",
        ".runtime-cache/build/tooling/ruff",
        ".runtime-cache/build/apps/webui",
        ".runtime-cache/test",
    }:
        return ("repo_exclusive", "safe_repo_cache", False)
    if name == ".runtime-cache":
        return ("repo_exclusive", "mixed_runtime_root", False)
    return ("repo_exclusive", "repo_runtime_misc", False)


def machine_entry_classification(name: str) -> tuple[str, str]:
    if name == "venv":
        return ("repo_fallback_host", "aggressive_host_cache")
    if name == "pycache":
        return ("repo_primary_shared_host", "safe_machine_cache")
    return ("repo_primary_shared_host", "rebuildable_machine_cache")


def render_status_icon(status: str) -> str:
    if status in {"over_error", "fail"}:
        return "❌"
    if status in {"over_warn", "retention-candidates", "shared-related"}:
        return "⚠️"
    if status in {"protected", "present"}:
        return "ℹ️"
    return "✅"


def _json_exit_code(*, warnings: list[str], errors: list[str]) -> int:
    # JSON mode is consumed by tests and follow-on automation as a machine-readable
    # report surface, so it should stay readable even when drift is detected.
    return 0


def main() -> int:
    inspect_docker_runtime = importlib.import_module("tooling.scripts.docker_runtime_inventory").inspect_docker_runtime
    record_runtime_governance = importlib.import_module("tooling.scripts.runtime_governance_report").record_runtime_governance

    parser = argparse.ArgumentParser(description="Monitor cache sizes")
    parser.add_argument("--root", type=str, default=".", help="Repository root path (default: current directory)")
    parser.add_argument(
        "--contract",
        type=str,
        default="contracts/runtime/filesystem_layout.yaml",
        help="Runtime filesystem contract path relative to repo root",
    )
    parser.add_argument("--warn-mb", type=float, default=None, help="Override repo runtime warn threshold in MB")
    parser.add_argument("--error-mb", type=float, default=None, help="Override repo runtime error threshold in MB")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument(
        "--require-docker-runtime",
        action="store_true",
        help="Fail when docker runtime inspection is unavailable",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    if not repo_root.exists():
        print(f"❌ check_cache_size: repo root not found: {repo_root}", file=sys.stderr)
        return 2

    contract_path = repo_root / args.contract
    contract = load_contract(contract_path)
    budgets = dict(contract.get("budgets_mb", {}))
    warn_mb = float(args.warn_mb if args.warn_mb is not None else budgets.get("repo_runtime_warn", 256))
    error_mb = float(args.error_mb if args.error_mb is not None else budgets.get("repo_runtime_error", 512))
    machine_warn_mb = float(budgets.get("machine_cache_warn", 768))
    machine_error_mb = float(budgets.get("machine_cache_error", 1280))
    docker_warn_mb = float(budgets.get("docker_runtime_warn", 4096))
    docker_error_mb = float(budgets.get("docker_runtime_error", 6144))
    docker_build_warn_mb = float(budgets.get("docker_build_cache_warn", 2048))
    docker_build_error_mb = float(budgets.get("docker_build_cache_error", 4096))
    retention = dict(contract.get("retention", {}))
    now = time.time()

    run_id = f"check-cache-size-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}"
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    start_ts = int(time.time())

    machine_cache = dict(contract.get("machine_cache", {}))
    workspace_runtime = dict(contract.get("workspace_runtime", {}))
    in_container = os.environ.get("MOVI_IN_CONTAINER", "0") == "1"

    machine_root = resolve_path(
        repo_root,
        str(machine_cache.get("root", "~/.cache/fileyard")),
        env_name="GOVERNANCE_MACHINE_CACHE_ROOT",
    )
    machine_targets = {
        "pycache": resolve_path(repo_root, str(machine_root / "pycache"), env_name="PYTHONPYCACHEPREFIX"),
        "pip": resolve_path(repo_root, str(machine_root / "pip"), env_name="PIP_CACHE_DIR"),
        "npm": resolve_path(repo_root, str(machine_root / "npm"), env_name="NPM_CONFIG_CACHE"),
        "playwright": resolve_path(repo_root, str(machine_root / "playwright"), env_name="PLAYWRIGHT_BROWSERS_PATH"),
        "xdg": resolve_path(repo_root, str(machine_root / "xdg"), env_name="XDG_CACHE_HOME"),
        "venv": resolve_path(repo_root, str(machine_root / "venv/default"), env_name="MOVI_VENV_DIR"),
    }

    run_root = resolve_path(
        repo_root,
        str(workspace_runtime.get("run_bundle_root", "~/.fileyard/workspaces/default/.movi/runs")),
        env_name="MOVI_RUN_BUNDLE_ROOT",
    )
    artifact_root = resolve_path(
        repo_root,
        str(workspace_runtime.get("artifact_root", "~/.fileyard/workspaces/default/.movi/artifacts")),
        env_name="MOVI_ARTIFACT_ROOT",
    )

    repo_targets = {
        ".runtime-cache": repo_root / ".runtime-cache",
        ".runtime-cache/build/tooling/mypy": repo_root / ".runtime-cache" / "build" / "tooling" / "mypy",
        ".runtime-cache/build/tooling/ruff": repo_root / ".runtime-cache" / "build" / "tooling" / "ruff",
        ".runtime-cache/build/apps/webui": repo_root / ".runtime-cache" / "build" / "apps" / "webui",
        ".runtime-cache/test": repo_root / ".runtime-cache" / "test",
        ".runtime-cache/logs/quality-gate": repo_root / ".runtime-cache" / "logs" / "quality-gate",
        ".runtime-cache/logs/scancode": repo_root / ".runtime-cache" / "logs" / "scancode",
        ".runtime-cache/ci": repo_root / ".runtime-cache" / "ci",
    }

    results: dict[str, dict[str, Any]] = {
        "repo_local": {"entries": []},
        "machine_cache": {"entries": []},
        "workspace_evidence": {"entries": []},
        "docker_runtime": {"entries": []},
    }
    warnings: list[str] = []
    errors: list[str] = []

    repo_total_mb = 0.0
    for name, path in repo_targets.items():
        size_mb = get_dir_size_mb(path)
        if name == ".runtime-cache":
            repo_total_mb = size_mb
        ownership_class, reclaim_class, protected = repo_entry_classification(name)
        status = status_for_threshold(size_mb, warn_mb, error_mb)
        results["repo_local"]["entries"].append(
            bucket_entry(
                path_or_object=name,
                size_mb=size_mb,
                ownership_class=ownership_class,
                reclaim_class=reclaim_class,
                protected=protected,
                exists_or_present=path.exists(),
                status=status,
            )
        )
        if name == ".runtime-cache":
            if size_mb >= error_mb:
                errors.append(f"repo_local: {size_mb:.1f}MB (exceeds {error_mb:.1f}MB limit)")
            elif size_mb >= warn_mb:
                warnings.append(f"repo_local: {size_mb:.1f}MB (exceeds {warn_mb:.1f}MB threshold)")

    results["repo_local"]["_total"] = {
        "size_mb": round(repo_total_mb, 2),
        "warn_mb": round(warn_mb, 2),
        "error_mb": round(error_mb, 2),
        "cleanup_cmd": REPO_CLEANUP_CMD,
    }

    machine_total_mb = 0.0
    for name, path in machine_targets.items():
        size_mb = get_dir_size_mb(path)
        machine_total_mb += size_mb
        ownership_class, reclaim_class = machine_entry_classification(name)
        results["machine_cache"]["entries"].append(
            bucket_entry(
                path_or_object=str(path),
                size_mb=size_mb,
                ownership_class=ownership_class,
                reclaim_class=reclaim_class,
                protected=False,
                exists_or_present=path.exists(),
                status="present" if path.exists() else "missing",
                extra={"target_name": name},
            )
        )
    results["machine_cache"]["_total"] = {
        "size_mb": round(machine_total_mb, 2),
        "warn_mb": round(machine_warn_mb, 2),
        "error_mb": round(machine_error_mb, 2),
        "cleanup_cmds": [MACHINE_SAFE_CLEANUP_CMD, MACHINE_REBUILDABLE_CLEANUP_CMD, MACHINE_AGGRESSIVE_CLEANUP_CMD],
        "budget_enforced": not in_container,
    }
    if not in_container:
        if machine_total_mb >= machine_error_mb:
            errors.append(f"machine cache: {machine_total_mb:.1f}MB (exceeds {machine_error_mb:.1f}MB limit)")
        elif machine_total_mb >= machine_warn_mb:
            warnings.append(f"machine cache: {machine_total_mb:.1f}MB (exceeds {machine_warn_mb:.1f}MB threshold)")

    workspace_runs_days = float(retention.get("workspace_runs_days", 14))
    workspace_runs_keep_latest = int(retention.get("workspace_runs_keep_latest", 50))
    workspace_artifacts_days = float(retention.get("workspace_artifacts_days", 14))
    workspace_failed_artifacts_days = float(retention.get("workspace_failed_artifacts_days", 30))

    run_dirs = [path for path in iter_direct_children(run_root) if path.is_dir()]
    protected_run_dirs = set(run_dirs[:workspace_runs_keep_latest])
    stale_run_candidates: list[str] = []
    for path in run_dirs:
        age_days = (now - path.stat().st_mtime) / 86400.0
        if path in protected_run_dirs:
            continue
        if age_days > workspace_runs_days:
            stale_run_candidates.append(path.name)

    artifact_candidates: list[str] = []
    managed_artifact_roots = [
        artifact_root / "ai-eval",
        artifact_root / "value-proof",
        artifact_root / "report",
        artifact_root / "rollback",
        artifact_root / "web_api" / "jobs",
        artifact_root / "web_api" / "csv",
        artifact_root / "web_api" / "uploads",
    ]
    for root in managed_artifact_roots:
        for path in iter_direct_children(root):
            age_days = (now - path.stat().st_mtime) / 86400.0
            threshold_days = workspace_failed_artifacts_days if path_is_failure_like(path) else workspace_artifacts_days
            if age_days > threshold_days:
                artifact_candidates.append(path.relative_to(artifact_root).as_posix())

    run_root_size_mb = get_dir_size_mb(run_root)
    artifact_root_size_mb = get_dir_size_mb(artifact_root)
    results["workspace_evidence"]["entries"] = [
        bucket_entry(
            path_or_object=str(run_root),
            size_mb=run_root_size_mb,
            ownership_class="repo_workspace",
            reclaim_class="workspace_run_retention",
            protected=True,
            exists_or_present=run_root.exists(),
            status="retention-candidates" if stale_run_candidates else "within_policy",
            extra={
                "candidate_count": len(stale_run_candidates),
                "keep_latest_runs": workspace_runs_keep_latest,
                "retention_days": workspace_runs_days,
            },
        ),
        bucket_entry(
            path_or_object=str(artifact_root),
            size_mb=artifact_root_size_mb,
            ownership_class="repo_workspace",
            reclaim_class="workspace_artifact_retention",
            protected=True,
            exists_or_present=artifact_root.exists(),
            status="retention-candidates" if artifact_candidates else "within_policy",
            extra={
                "candidate_count": len(artifact_candidates),
                "retention_days": workspace_artifacts_days,
                "failed_retention_days": workspace_failed_artifacts_days,
            },
        ),
    ]
    results["workspace_evidence"]["_total"] = {
        "run_root": str(run_root),
        "artifact_root": str(artifact_root),
        "run_count": len(run_dirs),
        "protected_run_count": min(len(run_dirs), workspace_runs_keep_latest),
        "stale_run_candidates": stale_run_candidates,
        "stale_artifact_candidates": artifact_candidates,
        "run_root_size_mb": round(run_root_size_mb, 2),
        "artifact_root_size_mb": round(artifact_root_size_mb, 2),
        "cleanup_cmd": WORKSPACE_CLEANUP_CMD,
    }
    if stale_run_candidates:
        warnings.append(f"workspace runs: {len(stale_run_candidates)} retention candidates (see {WORKSPACE_CLEANUP_CMD})")
    if artifact_candidates:
        warnings.append(f"workspace artifacts: {len(artifact_candidates)} retention candidates (see {WORKSPACE_CLEANUP_CMD})")

    docker_results = inspect_docker_runtime(repo_root, contract_path)
    results["docker_runtime"]["status"] = docker_results["status"]
    results["docker_runtime"]["entries"] = docker_results["entries"]
    build_cache_entry = next((entry for entry in docker_results["entries"] if entry["path_or_object"] == "docker build cache"), None)
    build_cache_mb = float(build_cache_entry.get("size_mb", 0)) if build_cache_entry else 0.0
    docker_total_mb = sum(
        float(entry.get("size_mb", 0)) for entry in docker_results["entries"] if entry["path_or_object"] != "docker build cache"
    )
    results["docker_runtime"]["_total"] = {
        "size_mb": round(docker_total_mb, 2),
        "warn_mb": round(docker_warn_mb, 2),
        "error_mb": round(docker_error_mb, 2),
        "build_cache_warn_mb": round(docker_build_warn_mb, 2),
        "build_cache_error_mb": round(docker_build_error_mb, 2),
        "cleanup_cmds": [DOCKER_AUDIT_CMD, DOCKER_REBUILDABLE_CMD, DOCKER_AGGRESSIVE_CMD],
        "build_cache": docker_results.get("build_cache", {}),
    }
    if docker_results["status"] == "unavailable":
        if args.require_docker_runtime:
            errors.append("docker runtime: unavailable (container-first runtime audit required but docker is not reachable)")
    else:
        if docker_total_mb >= docker_error_mb:
            errors.append(f"docker runtime: {docker_total_mb:.1f}MB (exceeds {docker_error_mb:.1f}MB limit)")
        elif docker_total_mb >= docker_warn_mb:
            warnings.append(f"docker runtime: {docker_total_mb:.1f}MB (exceeds {docker_warn_mb:.1f}MB threshold)")
        if build_cache_mb >= docker_build_error_mb:
            errors.append(f"docker build cache: {build_cache_mb:.1f}MB (exceeds {docker_build_error_mb:.1f}MB limit)")
        elif build_cache_mb >= docker_build_warn_mb:
            warnings.append(f"docker build cache: {build_cache_mb:.1f}MB (exceeds {docker_build_warn_mb:.1f}MB threshold)")

    flat_entries: list[dict[str, Any]] = []
    for bucket_name in ("repo_local", "machine_cache", "workspace_evidence", "docker_runtime"):
        for entry in results[bucket_name].get("entries", []):
            flat_entries.append({"bucket": bucket_name, **entry})
    totals = {
        "repo_local_mb": round(repo_total_mb, 2),
        "machine_cache_mb": round(machine_total_mb, 2),
        "workspace_runs_mb": round(run_root_size_mb, 2),
        "workspace_artifacts_mb": round(artifact_root_size_mb, 2),
        "docker_runtime_mb": round(docker_total_mb, 2),
        "warnings": warnings,
        "errors": errors,
    }

    status = "success"
    exit_code = 0
    if errors or warnings:
        status = "fail"
        exit_code = 1

    record_runtime_governance(
        repo_root=repo_root,
        command="check_cache_size",
        action_kind="audit",
        bucket="all",
        target="check_cache_size",
        dry_run=True,
        run_id=run_id,
        started_at=started_at,
        start_ts=start_ts,
        status=status,
        message="runtime cache audit completed",
        ownership_class="repo_governance",
        reclaim_class="audit_only",
        entries=flat_entries,
        totals=totals,
        extra={"contract_path": args.contract, "require_docker_runtime": args.require_docker_runtime},
    )

    if args.json:
        json.dump(results, sys.stdout, indent=2)
        print()
        return _json_exit_code(warnings=warnings, errors=errors)

    print("==> Repo-local runtime report")
    for entry in results["repo_local"]["entries"]:
        icon = render_status_icon(str(entry["status"]))
        exists = "exists" if bool(entry["exists_or_present"]) else "missing"
        print(f"{icon} {entry['path_or_object']:34s} {float(entry['size_mb']):8.1f} MB  ({exists}; {entry['reclaim_class']})")
    print(f"\n📊 Repo-local runtime size: {repo_total_mb:.1f} MB")
    print(f"📏 Runtime budget thresholds: warn={warn_mb:.1f}MB error={error_mb:.1f}MB")
    print(f"🧹 Repo-local cleanup: {REPO_CLEANUP_CMD}")

    print("\n==> Machine-cache report")
    for entry in results["machine_cache"]["entries"]:
        icon = render_status_icon(str(entry["status"]))
        exists = "exists" if bool(entry["exists_or_present"]) else "missing"
        target_name = entry.get("target_name", "")
        print(f"{icon} {target_name:20s} {float(entry['size_mb']):8.1f} MB  ({exists}; {entry['reclaim_class']})")
    print(f"\n📦 Machine-cache size: {machine_total_mb:.1f} MB")
    if in_container:
        print(
            "📏 Machine-cache thresholds: container-first in-container paths are informational only; "
            "host-side budget enforcement is skipped"
        )
    else:
        print(f"📏 Machine-cache thresholds: warn={machine_warn_mb:.1f}MB error={machine_error_mb:.1f}MB")
    print("🧹 Machine-cache cleanup:")
    print(f"  {MACHINE_SAFE_CLEANUP_CMD}")
    print(f"  {MACHINE_REBUILDABLE_CLEANUP_CMD}")
    print(f"  {MACHINE_AGGRESSIVE_CLEANUP_CMD}")

    workspace_data = results["workspace_evidence"]["_total"]
    print("\n==> Workspace evidence retention report")
    for entry in results["workspace_evidence"]["entries"]:
        icon = render_status_icon(str(entry["status"]))
        print(
            f"{icon} {entry['path_or_object']} size={float(entry['size_mb']):.1f}MB "
            f"candidates={entry.get('candidate_count', 0)} reclaim_class={entry['reclaim_class']}"
        )
    print(f"📁 Runs root: {workspace_data['run_root']}")
    print(f"📁 Artifact root: {workspace_data['artifact_root']}")
    print(f"🗂️ Run retention: keep_latest={workspace_runs_keep_latest} days={workspace_runs_days:.0f}")
    print(f"🧾 Artifact retention: days={workspace_artifacts_days:.0f} failed_days={workspace_failed_artifacts_days:.0f}")
    print(f"🧹 Workspace cleanup: {WORKSPACE_CLEANUP_CMD}")

    print("\n==> Docker runtime report")
    if docker_results["status"] == "unavailable":
        print("⚠️ docker runtime unavailable (docker CLI or daemon not reachable)")
    else:
        for entry in results["docker_runtime"]["entries"]:
            icon = render_status_icon(str(entry["status"]))
            extra = ""
            if "policy_size_mb" in entry or "artifact_size_mb" in entry:
                extra = f" policy={float(entry.get('policy_size_mb', 0)):.1f}MB artifact={float(entry.get('artifact_size_mb', 0)):.1f}MB"
            print(
                f"{icon} {entry['path_or_object']:34s} {float(entry['size_mb']):8.1f} MB"
                f"  ({entry['status']}; {entry['reclaim_class']}){extra}"
            )
    print(f"\n🐳 Docker-runtime thresholds: warn={docker_warn_mb:.1f}MB error={docker_error_mb:.1f}MB")
    print(f"🐳 Docker build-cache thresholds: warn={docker_build_warn_mb:.1f}MB error={docker_build_error_mb:.1f}MB")
    print("🧹 Docker-runtime cleanup:")
    print(f"  {DOCKER_AUDIT_CMD}")
    print(f"  {DOCKER_REBUILDABLE_CMD}")
    print(f"  {DOCKER_AGGRESSIVE_CMD}")

    if errors:
        print("\n❌ Errors:")
        for err in errors:
            print(f"  - {err}")
        print("\nAction required: choose the matching cleanup rail above (repo-local / machine-cache / docker-runtime / workspace)")
        return exit_code

    if warnings:
        print("\n⚠️ Warnings:")
        for warn in warnings:
            print(f"  - {warn}")
        print("\nRecommendation: choose the matching cleanup rail above (repo-local / machine-cache / docker-runtime / workspace)")
        return exit_code

    print("\n✅ Repo-local runtime, machine cache, workspace evidence, and docker runtime are within current policy")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
