from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml  # type: ignore[import-untyped]


@dataclass(frozen=True)
class StrategyPack:
    id: str
    name: str
    description: str
    categories: tuple[str, ...]
    model: str = ""
    workers: int = 1
    review_confidence_threshold: float = 0.8
    default_rule_ids: tuple[str, ...] = ()
    default_template_patterns: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "categories": list(self.categories),
            "model": self.model,
            "workers": self.workers,
            "review_confidence_threshold": self.review_confidence_threshold,
            "default_rule_ids": list(self.default_rule_ids),
            "default_template_patterns": list(self.default_template_patterns),
            "defaults": {
                "model": self.model,
                "workers": self.workers,
                "categories": list(self.categories),
                "review_confidence_threshold": self.review_confidence_threshold,
                "default_rule_ids": list(self.default_rule_ids),
                "default_template_patterns": list(self.default_template_patterns),
            },
            "explainability": {
                "setup_note": f"Use {self.name} when the workspace mostly contains {', '.join(self.categories) or 'mixed'} intake.",
                "inbox_note": (
                    f"Bias inbox analyze defaults toward {', '.join(self.categories) or 'mixed'} batches without bypassing review."
                ),
                "analyze_note": (
                    f"Default analyze settings: model {self.model or 'workspace default'}, "
                    f"{self.workers} worker(s), review threshold {self.review_confidence_threshold:.2f}."
                ),
            },
        }


def strategy_pack_paths(repo_root: str | Path) -> List[Path]:
    root = Path(repo_root).resolve() / "contracts" / "strategies"
    if not root.exists():
        return []
    return sorted(path for path in root.glob("*.yaml") if path.is_file())


def load_strategy_packs(repo_root: str | Path) -> List[StrategyPack]:
    packs: List[StrategyPack] = []
    for path in strategy_pack_paths(repo_root):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        pack = StrategyPack(
            id=str(data.get("id", path.stem)).strip(),
            name=str(data.get("name", path.stem.replace("-", " ").title())).strip(),
            description=str(data.get("description", "")).strip(),
            categories=tuple(str(item).strip() for item in data.get("categories", []) if str(item).strip()),
            model=str(data.get("model", "")).strip(),
            workers=max(int(data.get("workers", 1) or 1), 1),
            review_confidence_threshold=float(data.get("review_confidence_threshold", 0.8) or 0.8),
            default_rule_ids=tuple(str(item).strip() for item in data.get("default_rule_ids", []) if str(item).strip()),
            default_template_patterns=tuple(str(item).strip() for item in data.get("default_template_patterns", []) if str(item).strip()),
        )
        if pack.id:
            packs.append(pack)
    return packs


def strategy_pack_by_id(repo_root: str | Path, pack_id: str) -> StrategyPack | None:
    for pack in load_strategy_packs(repo_root):
        if pack.id == pack_id:
            return pack
    return None
