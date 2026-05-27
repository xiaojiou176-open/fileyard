from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class LearnedRule:
    id: str
    signal_key: str
    signal_value: str
    suggestion_type: str
    suggestion_value: str
    confidence: float
    count: int
    confidence_label: str
    strength: str
    reuse_scope: str
    source: str
    reason: str
    explanation: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "signal_key": self.signal_key,
            "signal_value": self.signal_value,
            "suggestion_type": self.suggestion_type,
            "suggestion_value": self.suggestion_value,
            "confidence": self.confidence,
            "count": self.count,
            "confidence_label": self.confidence_label,
            "strength": self.strength,
            "reuse_scope": self.reuse_scope,
            "source": self.source,
            "reason": self.reason,
            "explanation": self.explanation,
            "updated_at": self.updated_at,
        }


def learned_rule_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser() / ".fileorganize" / "preferences" / "learned_rules.json"


def load_learned_rules(workspace_root: str | Path) -> List[LearnedRule]:
    path = learned_rule_path(workspace_root)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    rules: List[LearnedRule] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            rules.append(
                LearnedRule(
                    id=str(item.get("id", "")).strip(),
                    signal_key=str(item.get("signal_key", "")).strip(),
                    signal_value=str(item.get("signal_value", "")).strip(),
                    suggestion_type=str(item.get("suggestion_type", "")).strip(),
                    suggestion_value=str(item.get("suggestion_value", "")).strip(),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    count=int(item.get("count", 0) or 0),
                    confidence_label=str(item.get("confidence_label", "") or _confidence_label(item)).strip() or "weak",
                    strength=str(item.get("strength", "") or _strength_label(item)).strip() or "weak",
                    reuse_scope=str(item.get("reuse_scope", "") or _reuse_scope(item)).strip() or "transient",
                    source=str(item.get("source", "") or "workspace_review_learning_v1").strip(),
                    reason=str(item.get("reason", "") or _reason_text(item)).strip(),
                    explanation=str(item.get("explanation", "") or item.get("reason", "") or _reason_text(item)).strip(),
                    updated_at=str(item.get("updated_at", "")).strip(),
                )
            )
        except (TypeError, ValueError):
            continue
    return [rule for rule in rules if rule.id]


def save_learned_rules(workspace_root: str | Path, rules: Iterable[LearnedRule], *, updated_at: str) -> Path:
    path = learned_rule_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": updated_at,
        "items": [rule.to_dict() for rule in rules],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _confidence_label(item: Dict[str, Any]) -> str:
    confidence = float(item.get("confidence", 0.0) or 0.0)
    count = int(item.get("count", 0) or 0)
    if confidence >= 0.9 or count >= 5:
        return "high"
    if confidence >= 0.75 or count >= 3:
        return "medium"
    return "weak"


def _strength_label(item: Dict[str, Any]) -> str:
    confidence = float(item.get("confidence", 0.0) or 0.0)
    count = int(item.get("count", 0) or 0)
    if confidence >= 0.85 and count >= 3:
        return "strong"
    if confidence >= 0.7 or count >= 2:
        return "medium"
    return "weak"


def _reuse_scope(item: Dict[str, Any]) -> str:
    count = int(item.get("count", 0) or 0)
    return "reusable" if count >= 2 else "transient"


def _reason_text(item: Dict[str, Any]) -> str:
    signal_key = str(item.get("signal_key", "") or "signal")
    signal_value = str(item.get("signal_value", "") or "unknown")
    suggestion_value = str(item.get("suggestion_value", "") or "unknown")
    count = int(item.get("count", 0) or 0)
    return f"Observed {count} accepted review edit(s) mapping {signal_key}={signal_value} to {suggestion_value}."
