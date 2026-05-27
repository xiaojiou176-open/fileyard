from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

DEFAULT_WORKSPACE_ROOT = "~/.fileorganize/workspaces/default"


def workspace_root() -> Path:
    return Path(os.environ.get("FILEORGANIZE_WORKSPACE_ROOT", DEFAULT_WORKSPACE_ROOT)).expanduser()


def runtime_env_file(root: Path | None = None) -> Path:
    base = root.expanduser() if root is not None else workspace_root()
    return base / ".fileorganize" / "env" / "runtime.env"


def read_runtime_env(root: Path | None = None) -> dict[str, str]:
    env_path = runtime_env_file(root)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed = value.strip()
        if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {'"', "'"}:
            parsed = parsed[1:-1]
        values[key.strip()] = parsed.strip()
    return values


def resolve_env_value(name: str, default: str = "", *, root: Path | None = None) -> str:
    current = str(os.environ.get(name, "")).strip()
    if current:
        return current
    return read_runtime_env(root).get(name, default)


def resolve_path_value(name: str, default: str, *, root: Path | None = None) -> Path:
    return Path(resolve_env_value(name, default, root=root)).expanduser()


def _format_env_value(value: str) -> str:
    needs_quotes = any(ch.isspace() for ch in value) or any(ch in value for ch in ["#", '"', "'"])
    if needs_quotes:
        return json.dumps(value, ensure_ascii=True)
    return value


def upsert_runtime_env(updates: Mapping[str, str | None], *, root: Path | None = None) -> Path:
    env_path = runtime_env_file(root)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    handled: set[str] = set()
    next_lines: list[str] = []

    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            next_lines.append(raw_line)
            continue
        raw_key, _ = raw_line.split("=", 1)
        key = raw_key.strip()
        if key not in updates:
            next_lines.append(raw_line)
            continue
        handled.add(key)
        value = updates[key]
        if value is None or not str(value).strip():
            continue
        next_lines.append(f"{key}={_format_env_value(str(value).strip())}")

    for key, value in updates.items():
        if key in handled or value is None or not str(value).strip():
            continue
        next_lines.append(f"{key}={_format_env_value(str(value).strip())}")

    env_path.write_text("\n".join(next_lines).rstrip() + ("\n" if next_lines else ""), encoding="utf-8")
    return env_path


def mask_secret(value: str, *, prefix: int = 3, suffix: int = 4) -> str:
    trimmed = str(value or "").strip()
    if not trimmed:
        return ""
    if len(trimmed) <= prefix + suffix:
        return "*" * len(trimmed)
    return f"{trimmed[:prefix]}{'*' * (len(trimmed) - prefix - suffix)}{trimmed[-suffix:]}"
