from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from packages.domain.strategy_pack_registry import StrategyPack, load_strategy_packs, strategy_pack_by_id
from packages.infrastructure.preference_store import read_named_items, write_named_items

ACTIVE_PACK_PREFERENCE_NAME = "strategy_packs"
ACTIVE_PACK_PREFERENCE_KEY = "active"


def list_strategy_pack_payloads(repo_root: str | Path) -> List[Dict[str, Any]]:
    return [pack.to_dict() for pack in load_strategy_packs(repo_root)]


def get_active_strategy_pack_id(workspace_root: str | Path) -> str:
    items = read_named_items(workspace_root, ACTIVE_PACK_PREFERENCE_NAME)
    payload = dict(items.get(ACTIVE_PACK_PREFERENCE_KEY, {}) or {}).get("value", {})
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("pack_id", "")).strip()


def set_active_strategy_pack_id(workspace_root: str | Path, pack_id: str, *, updated_at: str) -> None:
    items = read_named_items(workspace_root, ACTIVE_PACK_PREFERENCE_NAME)
    current = dict(items.get(ACTIVE_PACK_PREFERENCE_KEY, {}) or {})
    items[ACTIVE_PACK_PREFERENCE_KEY] = {
        "value": {"pack_id": pack_id},
        "created_at": current.get("created_at", updated_at),
        "updated_at": updated_at,
    }
    write_named_items(workspace_root, ACTIVE_PACK_PREFERENCE_NAME, items, updated_at=updated_at)


def get_active_strategy_pack(repo_root: str | Path, workspace_root: str | Path) -> StrategyPack | None:
    pack_id = get_active_strategy_pack_id(workspace_root)
    if not pack_id:
        return None
    return strategy_pack_by_id(repo_root, pack_id)
