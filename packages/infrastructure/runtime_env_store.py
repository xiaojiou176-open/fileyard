from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

DEFAULT_WORKSPACE_ROOT = "~/.fileman/workspaces/default"
RUNTIME_ENV_RELATIVE_PATH = Path(".fileman") / "env" / "runtime.env"


def runtime_env_file(workspace_root: str | Path | None = None) -> Path:
    resolved_workspace = Path(workspace_root or os.environ.get("FILEMAN_WORKSPACE_ROOT", DEFAULT_WORKSPACE_ROOT)).expanduser()
    return resolved_workspace / RUNTIME_ENV_RELATIVE_PATH


def read_runtime_env_map(workspace_root: str | Path | None = None) -> dict[str, str]:
    env_path = runtime_env_file(workspace_root)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if not normalized_key:
            continue
        parsed = value.strip()
        if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {'"', "'"}:
            parsed = parsed[1:-1]
        values[normalized_key] = parsed.strip()
    return values


def read_runtime_env_value(name: str, workspace_root: str | Path | None = None) -> str:
    return read_runtime_env_map(workspace_root).get(name, "")


def resolve_env_prefer_runtime_env(name: str, default: str = "", workspace_root: str | Path | None = None) -> str:
    value = str(os.environ.get(name, "")).strip()
    if value:
        return value
    runtime_value = read_runtime_env_value(name, workspace_root)
    if runtime_value:
        return runtime_value
    return default


def write_runtime_env_values(
    updates: Mapping[str, str | None],
    *,
    workspace_root: str | Path | None = None,
) -> Path:
    env_path = runtime_env_file(workspace_root)
    values = read_runtime_env_map(workspace_root)

    for key, value in updates.items():
        if value is None:
            values.pop(key, None)
            continue
        values[key] = str(value).strip()

    env_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_lines = [f"{key}={_quote_env_value(value)}" for key, value in values.items()]
    rendered = "\n".join(rendered_lines)
    if rendered:
        rendered += "\n"
    env_path.write_text(rendered, encoding="utf-8")
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass
    return env_path


def _quote_env_value(value: str) -> str:
    if value == "":
        return '""'
    if any(char.isspace() for char in value) or any(char in value for char in "#=\"'"):
        return json.dumps(value, ensure_ascii=False)
    return value
