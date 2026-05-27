from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

PREFERENCE_ROOT_RELATIVE_PATH = Path(".fileorganize") / "preferences"
LEGACY_WEB_API_PREF_ROOT_RELATIVE_PATH = Path(".fileorganize") / "artifacts" / "web_api" / "preferences"


def preference_root(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser() / PREFERENCE_ROOT_RELATIVE_PATH


def legacy_preference_root(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser() / LEGACY_WEB_API_PREF_ROOT_RELATIVE_PATH


def preference_file(workspace_root: str | Path, name: str) -> Path:
    return preference_root(workspace_root) / f"{name}.json"


def legacy_preference_file(workspace_root: str | Path, name: str) -> Path:
    return legacy_preference_root(workspace_root) / f"{name}.json"


def read_named_items(workspace_root: str | Path, name: str) -> Dict[str, Dict[str, Any]]:
    current_path = preference_file(workspace_root, name)
    legacy_path = legacy_preference_file(workspace_root, name)
    payload = _read_payload(current_path)
    if payload is None:
        payload = _read_payload(legacy_path)
    return _normalize_items(payload)


def write_named_items(
    workspace_root: str | Path,
    name: str,
    items: Dict[str, Dict[str, Any]],
    *,
    updated_at: str,
) -> Path:
    target = preference_file(workspace_root, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = {"updated_at": updated_at, "items": items}
    target.write_text(json.dumps(rendered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def migrate_legacy_named_items(
    workspace_root: str | Path,
    name: str,
    *,
    updated_at: str,
) -> Path | None:
    current_path = preference_file(workspace_root, name)
    if current_path.exists():
        return None
    legacy_path = legacy_preference_file(workspace_root, name)
    payload = _read_payload(legacy_path)
    if payload is None:
        return None
    return write_named_items(workspace_root, name, _normalize_items(payload), updated_at=updated_at)


def _read_payload(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _normalize_items(payload: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
    if not payload:
        return {}
    items = payload.get("items", {})
    if not isinstance(items, dict):
        return {}
    normalized: Dict[str, Dict[str, Any]] = {}
    for key, value in items.items():
        if isinstance(key, str) and isinstance(value, dict):
            normalized[key] = dict(value)
    return normalized
