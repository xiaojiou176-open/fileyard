from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping

from packages.infrastructure.learned_rule_store import LearnedRule


@dataclass(frozen=True)
class LearnedSuggestion:
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
    scope_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
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
            "scope_reason": self.scope_reason,
        }


def learn_category_rules(
    base_rows: Iterable[Mapping[str, Any]],
    edited_rows: Iterable[Mapping[str, Any]],
    *,
    updated_at: str,
) -> List[LearnedRule]:
    base_map = {str(row.get("id", row.get("row_id", "")) or ""): row for row in base_rows}
    counter: Counter[tuple[str, str]] = Counter()
    for edited in edited_rows:
        row_id = str(edited.get("id", edited.get("row_id", "")) or "")
        if not row_id or row_id not in base_map:
            continue
        base = base_map[row_id]
        base_category = _row_category(base)
        next_category = _row_category(edited)
        if not next_category or next_category == base_category:
            continue
        signal_value = str(edited.get("media_type", "") or "unknown")
        counter[(signal_value, next_category)] += 1

    rules: List[LearnedRule] = []
    for index, ((signal_value, suggestion_value), count) in enumerate(sorted(counter.items()), start=1):
        confidence = min(0.55 + count * 0.1, 0.95)
        rules.append(
            LearnedRule(
                id=f"learned-category-{index}",
                signal_key="media_type",
                signal_value=signal_value,
                suggestion_type="category",
                suggestion_value=suggestion_value,
                confidence=confidence,
                count=count,
                confidence_label=_confidence_label(confidence, count),
                strength=_strength_label(confidence, count),
                reuse_scope=_reuse_scope(count),
                source="workspace_review_learning_v1",
                reason=_reason_text("media_type", signal_value, suggestion_value, count),
                explanation=_reason_text("media_type", signal_value, suggestion_value, count),
                updated_at=updated_at,
            )
        )
    return rules


def suggest_for_row(row: Mapping[str, Any], learned_rules: Iterable[LearnedRule]) -> List[LearnedSuggestion]:
    media_type = str(row.get("media_type", "") or "unknown")
    suggestions: List[LearnedSuggestion] = []
    for rule in learned_rules:
        if rule.signal_key != "media_type":
            continue
        if rule.signal_value != media_type:
            continue
        suggestions.append(
            LearnedSuggestion(
                signal_key=rule.signal_key,
                signal_value=rule.signal_value,
                suggestion_type=rule.suggestion_type,
                suggestion_value=rule.suggestion_value,
                confidence=rule.confidence,
                count=rule.count,
                confidence_label=rule.confidence_label or _confidence_label(rule.confidence, rule.count),
                strength=rule.strength or _strength_label(rule.confidence, rule.count),
                reuse_scope=rule.reuse_scope or _reuse_scope(rule.count),
                source=rule.source or "workspace_review_learning_v1",
                reason=rule.reason or _reason_text(rule.signal_key, rule.signal_value, rule.suggestion_value, rule.count),
                explanation=rule.reason or _reason_text(rule.signal_key, rule.signal_value, rule.suggestion_value, rule.count),
                scope_reason=_scope_reason(rule.reuse_scope or _reuse_scope(rule.count), rule.count),
            )
        )
    suggestions.sort(key=lambda item: (-item.confidence, -item.count, item.suggestion_value))
    return suggestions


def _confidence_label(confidence: float, count: int) -> str:
    if confidence >= 0.9 or count >= 5:
        return "high"
    if confidence >= 0.75 or count >= 3:
        return "medium"
    return "weak"


def _strength_label(confidence: float, count: int) -> str:
    if confidence >= 0.85 and count >= 3:
        return "strong"
    if confidence >= 0.7 or count >= 2:
        return "medium"
    return "weak"


def _reuse_scope(count: int) -> str:
    return "reusable" if count >= 2 else "transient"


def _reason_text(signal_key: str, signal_value: str, suggestion_value: str, count: int) -> str:
    return f"Observed {count} accepted review edit(s) mapping {signal_key}={signal_value} to {suggestion_value}."


def _scope_reason(reuse_scope: str, count: int) -> str:
    if reuse_scope == "reusable":
        return f"Observed {count} accepted review edit(s); treat this as a reusable workspace preference suggestion."
    return "Only one accepted review edit is on record, so this stays a transient suggestion until it repeats."


def _row_category(row: Mapping[str, Any]) -> str:
    direct = str(row.get("category", "") or "").strip()
    if direct:
        return direct
    ai = row.get("ai", {})
    if isinstance(ai, Mapping):
        return str(ai.get("category", "") or "").strip()
    return ""
