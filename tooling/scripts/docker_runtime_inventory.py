#!/usr/bin/env python3
"""Docker runtime inventory helpers for quality_gate / pre-push cache observability."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - exercised by shell/e2e fixture path
    yaml = None  # type: ignore[assignment]

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True


def _run(command: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError:
        return None


def _size_text_to_kib(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if text == "0B":
        return 0
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)", text)
    if not match:
        return 0
    number = float(match.group(1))
    unit = match.group(2)
    factors = {
        "B": 1 / 1024,
        "kB": 1000 / 1024,
        "KB": 1000 / 1024,
        "MB": 1000 * 1000 / 1024,
        "GB": 1000 * 1000 * 1000 / 1024,
        "TB": 1000 * 1000 * 1000 * 1000 / 1024,
        "KiB": 1,
        "MiB": 1024,
        "GiB": 1024 * 1024,
        "TiB": 1024 * 1024 * 1024,
    }
    factor = factors.get(unit)
    if factor is None:
        return 0
    return int(round(number * factor))


def _kib_to_mb(size_kib: int) -> float:
    return round(size_kib / 1024, 2)


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise SystemExit(f"invalid yaml: {path}")
        return data
    return _load_simple_yaml(text, path)


def _load_simple_yaml(text: str, path: Path) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]

    def _parse_scalar(raw: str) -> Any:
        value = raw.strip()
        if value == "":
            return ""
        if value in {"true", "false"}:
            return value == "true"
        if re.fullmatch(r"-?\d+", value):
            return int(value)
        if re.fullmatch(r"-?\d+\.\d+", value):
            return float(value)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1:-1]
        return value

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        parent = stack[-1][1]
        if line.startswith("- "):
            item_value = _parse_scalar(line[2:])
            if not isinstance(parent, list):
                raise SystemExit(f"invalid yaml list structure: {path}")
            parent.append(item_value)
            continue

        key, _, raw_value = line.partition(":")
        if not _:
            raise SystemExit(f"invalid yaml mapping: {path}")
        key = key.strip()
        value = raw_value.strip()

        if value == "":
            next_container: Any
            next_container = [] if _next_non_comment_line_is_list(text, raw_line) else {}
            if not isinstance(parent, dict):
                raise SystemExit(f"invalid yaml nesting: {path}")
            parent[key] = next_container
            stack.append((indent, next_container))
            continue

        if not isinstance(parent, dict):
            raise SystemExit(f"invalid yaml scalar nesting: {path}")
        parent[key] = _parse_scalar(value)

    return root


def _next_non_comment_line_is_list(full_text: str, current_line: str) -> bool:
    seen_current = False
    for raw_line in full_text.splitlines():
        if not seen_current:
            if raw_line == current_line:
                seen_current = True
            continue
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped.startswith("- ")
    return False


def _read_defaults(repo_root: Path) -> dict[str, str]:
    defaults_path = repo_root / "contracts" / "governance" / "governance.defaults.env"
    values: dict[str, str] = {}
    if not defaults_path.exists():
        return values
    for raw in defaults_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _parse_image_unique_size(system_df: str, image_ref: str) -> int:
    repo, _, tag = image_ref.partition(":")
    in_images = False
    for raw in system_df.splitlines():
        line = raw.rstrip()
        if line.startswith("Images space usage:"):
            in_images = True
            continue
        if in_images and line.startswith("Containers space usage:"):
            break
        if not in_images or not line.strip() or line.startswith("REPOSITORY"):
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 8:
            continue
        row_repo, row_tag = parts[0], parts[1]
        if row_repo == repo and row_tag == tag:
            unique_size = parts[6]
            return _size_text_to_kib(unique_size)
    return 0


def _parse_build_cache_total(system_df: str) -> int:
    match = re.search(r"Build cache usage:\s*([0-9.]+\s*[A-Za-z]+)", system_df)
    if not match:
        return 0
    return _size_text_to_kib(match.group(1).replace(" ", ""))


def _parse_buildx_du_verbose(output: str) -> list[dict[str, Any]]:
    blocks = [block.strip() for block in output.split("\n\n") if block.strip()]
    entries: list[dict[str, Any]] = []
    for block in blocks:
        payload: dict[str, Any] = {}
        for raw in block.splitlines():
            if ":" not in raw:
                continue
            key, value = raw.split(":", 1)
            payload[key.strip().lower().replace(" ", "_")] = value.strip()
        if "id" not in payload:
            continue
        payload["size_kib"] = _size_text_to_kib(str(payload.get("size", "")))
        entries.append(payload)
    return entries


def _repo_specific_description(description: str) -> bool:
    return any(
        marker in description
        for marker in (
            "COPY tooling/requirements.lock.txt",
            "COPY tooling/requirements-dev.lock.txt",
            "COPY tooling/requirements.txt",
            "COPY apps/webui/package.json",
            "COPY apps/webui/package-lock.json",
        )
    )


def _repo_related_base_description(description: str, defaults: dict[str, str]) -> bool:
    markers = [
        defaults.get("GOVERNANCE_NODE_RUNTIME_IMAGE", ""),
        "mcr.microsoft.com/devcontainers/python:1-3.11-bullseye",
        "docker.io/library/node:24.8.0-bullseye",
    ]
    return any(marker and marker in description for marker in markers)


def inspect_docker_runtime(repo_root: Path, contract_path: Path) -> dict[str, Any]:
    contract = _load_yaml(contract_path)
    docker_contract = dict(contract.get("docker_runtime", {}))
    defaults = _read_defaults(repo_root)
    compose_project = str(docker_contract.get("compose_project", "fileman-web-stack"))
    canonical_image = str(docker_contract.get("canonical_image", "fileman-ci:local"))
    protected_volumes = [str(item) for item in docker_contract.get("protected_volumes", [])]
    optional_volumes = [str(item) for item in docker_contract.get("optional_volumes", [])]

    result: dict[str, Any] = {
        "status": "unavailable",
        "compose_project": compose_project,
        "canonical_image": canonical_image,
        "protected_volumes": protected_volumes,
        "optional_volumes": optional_volumes,
        "entries": [],
        "build_cache": {
            "total_kib": 0,
            "rebuildable_ids": [],
            "aggressive_ids": [],
            "repo_related_entry_count": 0,
        },
    }
    system_df_proc = _run(["docker", "system", "df", "-v"])
    if system_df_proc is None or system_df_proc.returncode != 0:
        return result
    system_df = system_df_proc.stdout
    result["status"] = "available"

    image_artifact_proc = _run(["docker", "image", "inspect", canonical_image, "--format", "{{.Size}}"])
    artifact_kib = 0
    image_present = image_artifact_proc is not None and image_artifact_proc.returncode == 0
    if image_present and image_artifact_proc is not None:
        try:
            artifact_kib = int(image_artifact_proc.stdout.strip()) // 1024
        except ValueError:
            artifact_kib = 0
    policy_kib = _parse_image_unique_size(system_df, canonical_image)
    result["entries"].append(
        {
            "path_or_object": f"docker image {canonical_image}",
            "size_mb": _kib_to_mb(policy_kib),
            "policy_size_mb": _kib_to_mb(policy_kib),
            "artifact_size_mb": _kib_to_mb(artifact_kib),
            "ownership_class": "repo_exclusive",
            "reclaim_class": "protected_canonical_image",
            "protected": True,
            "exists_or_present": image_present,
            "status": "protected" if image_present else "missing",
        }
    )

    for volume_name in [*protected_volumes, *optional_volumes]:
        inspect_proc = _run(["docker", "volume", "inspect", volume_name, "--format", "{{json .Labels}} {{.Mountpoint}}"])
        volume_present = inspect_proc is not None and inspect_proc.returncode == 0
        volume_kib = 0
        if volume_present and inspect_proc is not None:
            raw = inspect_proc.stdout.strip()
            parts = raw.split(" ", 1)
            mountpoint = parts[1] if len(parts) == 2 else ""
            if mountpoint:
                du_proc = _run(["du", "-sk", mountpoint])
                if du_proc is not None and du_proc.returncode == 0:
                    volume_kib = int(du_proc.stdout.split()[0])
        result["entries"].append(
            {
                "path_or_object": f"docker volume {volume_name}",
                "size_mb": _kib_to_mb(volume_kib),
                "ownership_class": "repo_exclusive",
                "reclaim_class": "protected_volume" if volume_name in protected_volumes else "optional_volume",
                "protected": volume_name in protected_volumes,
                "exists_or_present": volume_present,
                "status": (
                    "protected" if volume_name in protected_volumes and volume_present else ("present" if volume_present else "missing")
                ),
            }
        )

    buildx_proc = _run(["docker", "buildx", "du", "--verbose"])
    build_cache_total_kib = _parse_build_cache_total(system_df)
    rebuildable_ids: list[str] = []
    aggressive_ids: list[str] = []
    repo_related_count = 0
    rebuildable_kib = 0
    aggressive_kib = 0
    if buildx_proc is not None and buildx_proc.returncode == 0:
        for entry in _parse_buildx_du_verbose(buildx_proc.stdout):
            desc = str(entry.get("description", ""))
            entry_id = str(entry.get("id", ""))
            entry_size_kib = int(entry.get("size_kib", 0))
            if _repo_specific_description(desc):
                rebuildable_ids.append(entry_id)
                aggressive_ids.append(entry_id)
                repo_related_count += 1
                rebuildable_kib += entry_size_kib
                aggressive_kib += entry_size_kib
                continue
            if _repo_related_base_description(desc, defaults):
                aggressive_ids.append(entry_id)
                repo_related_count += 1
                aggressive_kib += entry_size_kib
    result["build_cache"] = {
        "total_kib": build_cache_total_kib,
        "rebuildable_kib": rebuildable_kib,
        "aggressive_kib": aggressive_kib,
        "rebuildable_ids": rebuildable_ids,
        "aggressive_ids": aggressive_ids,
        "repo_related_entry_count": repo_related_count,
    }
    result["entries"].append(
        {
            "path_or_object": "docker build cache",
            "size_mb": _kib_to_mb(aggressive_kib),
            "ownership_class": "repo_related_shared",
            "reclaim_class": "docker_build_cache_shared",
            "protected": False,
            "exists_or_present": aggressive_kib > 0,
            "status": "shared-related" if aggressive_kib > 0 else "missing",
            "repo_related_entry_count": repo_related_count,
            "rebuildable_entry_count": len(rebuildable_ids),
            "aggressive_entry_count": len(aggressive_ids),
            "shared_total_size_mb": _kib_to_mb(build_cache_total_kib),
            "rebuildable_size_mb": _kib_to_mb(rebuildable_kib),
            "aggressive_size_mb": _kib_to_mb(aggressive_kib),
        }
    )
    return result


def prune_docker_runtime(
    *,
    repo_root: Path,
    contract_path: Path,
    mode: str,
    include_image: bool,
    include_volumes: bool,
    dry_run: bool,
) -> dict[str, Any]:
    inventory = inspect_docker_runtime(repo_root, contract_path)
    if inventory["status"] != "available":
        return {
            "status": "unavailable",
            "entries": [],
            "totals": {"candidate_kib": 0, "reclaimed_kib": 0},
            "inventory": inventory,
        }

    build_cache = dict(inventory["build_cache"])
    canonical_image = str(inventory["canonical_image"])
    protected_volumes = list(inventory["protected_volumes"])
    optional_volumes = list(inventory["optional_volumes"])

    build_ids = list(build_cache["rebuildable_ids"] if mode == "rebuildable" else build_cache["aggressive_ids"])
    build_candidate_kib = int(build_cache["rebuildable_kib"] if mode == "rebuildable" else build_cache["aggressive_kib"])
    entries: list[dict[str, Any]] = []
    reclaimed_kib = 0

    if build_ids:
        entries.append(
            {
                "path_or_object": "docker build cache",
                "size_before_kib": build_candidate_kib,
                "size_after_kib": 0 if not dry_run else build_candidate_kib,
                "reclaimed_kib": 0 if dry_run else build_candidate_kib,
                "ownership_class": "repo_related_shared",
                "reclaim_class": f"docker_build_cache_{mode}",
                "protected": False,
                "exists_or_present": True,
                "status": "candidate",
            }
        )
        if not dry_run:
            if mode == "aggressive":
                _run(["docker", "buildx", "prune", "-f", "--all"])
            else:
                for cache_id in build_ids:
                    _run(["docker", "buildx", "prune", "-f", "--filter", f"id={cache_id}"])
            reclaimed_kib += build_candidate_kib

    if include_image:
        image_entry = next(
            (entry for entry in inventory["entries"] if entry["path_or_object"] == f"docker image {canonical_image}"),
            None,
        )
        policy_kib = int(round(float(image_entry.get("policy_size_mb", 0)) * 1024)) if image_entry else 0
        entries.append(
            {
                "path_or_object": f"docker image {canonical_image}",
                "size_before_kib": policy_kib,
                "size_after_kib": 0 if not dry_run else policy_kib,
                "reclaimed_kib": 0 if dry_run else policy_kib,
                "ownership_class": "repo_exclusive",
                "reclaim_class": "canonical_image_unlock",
                "protected": True,
                "exists_or_present": bool(image_entry and image_entry["exists_or_present"]),
                "status": "candidate",
            }
        )
        if not dry_run:
            _run(["docker", "image", "rm", "-f", canonical_image])
            reclaimed_kib += policy_kib

    if include_volumes:
        for volume_name in [*protected_volumes, *optional_volumes]:
            volume_entry = next(
                (entry for entry in inventory["entries"] if entry["path_or_object"] == f"docker volume {volume_name}"),
                None,
            )
            volume_kib = int(round(float(volume_entry.get("size_mb", 0)) * 1024)) if volume_entry else 0
            entries.append(
                {
                    "path_or_object": f"docker volume {volume_name}",
                    "size_before_kib": volume_kib,
                    "size_after_kib": 0 if not dry_run else volume_kib,
                    "reclaimed_kib": 0 if dry_run else volume_kib,
                    "ownership_class": "repo_exclusive",
                    "reclaim_class": "protected_volume_unlock" if volume_name in protected_volumes else "optional_volume_unlock",
                    "protected": volume_name in protected_volumes,
                    "exists_or_present": bool(volume_entry and volume_entry["exists_or_present"]),
                    "status": "candidate",
                }
            )
            if not dry_run:
                _run(["docker", "volume", "rm", "-f", volume_name])
                reclaimed_kib += volume_kib

    candidate_kib = sum(int(entry.get("size_before_kib", 0)) for entry in entries)
    return {
        "status": "success",
        "entries": entries,
        "totals": {
            "candidate_kib": candidate_kib,
            "reclaimed_kib": reclaimed_kib,
        },
        "inventory": inventory,
    }
