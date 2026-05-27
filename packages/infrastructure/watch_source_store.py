from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class WatchSource:
    id: str
    name: str
    input_root: str
    enabled: bool
    strategy_pack_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "input_root": self.input_root,
            "enabled": self.enabled,
            "strategy_pack_id": self.strategy_pack_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def watch_source_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser() / ".fileyard" / "preferences" / "watch_sources.json"


def load_watch_sources(workspace_root: str | Path) -> List[WatchSource]:
    path = watch_source_path(workspace_root)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    sources: List[WatchSource] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        source = WatchSource(
            id=str(item.get("id", "")).strip(),
            name=str(item.get("name", "")).strip(),
            input_root=str(item.get("input_root", "")).strip(),
            enabled=bool(item.get("enabled", True)),
            strategy_pack_id=str(item.get("strategy_pack_id", "")).strip(),
            created_at=str(item.get("created_at", "")).strip(),
            updated_at=str(item.get("updated_at", "")).strip(),
        )
        if source.id:
            sources.append(source)
    return sources


def save_watch_sources(workspace_root: str | Path, sources: List[WatchSource], *, updated_at: str) -> Path:
    path = watch_source_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": updated_at,
        "items": [source.to_dict() for source in sources],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
