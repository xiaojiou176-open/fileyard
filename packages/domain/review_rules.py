from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


@dataclass(frozen=True)
class ReviewRuleCondition:
    query: str = ""
    statuses: tuple[str, ...] = ()
    media_types: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    review_buckets: tuple[str, ...] = ()
    min_confidence: float | None = None
    max_confidence: float | None = None
    has_conflict: bool | None = None
    ignore_state: bool | None = None


@dataclass(frozen=True)
class ReviewRuleAction:
    set_category: str | None = None
    set_ignore: bool | None = None
    target_pattern: str | None = None


@dataclass(frozen=True)
class ReviewRule:
    id: str
    name: str
    scope: str
    conditions: ReviewRuleCondition
    actions: ReviewRuleAction
    description: str = ""
    version: int = 1
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReviewRule":
        conditions = payload.get("conditions", {}) if isinstance(payload.get("conditions"), dict) else {}
        actions = payload.get("actions", {}) if isinstance(payload.get("actions"), dict) else {}
        return cls(
            id=str(payload.get("id", "") or payload.get("key", "")).strip(),
            name=str(payload.get("name", "")).strip(),
            scope=str(payload.get("scope", "manifest")).strip() or "manifest",
            description=str(payload.get("description", "")).strip(),
            version=int(payload.get("version", 1) or 1),
            created_at=str(payload.get("created_at", "")).strip(),
            updated_at=str(payload.get("updated_at", "")).strip(),
            conditions=ReviewRuleCondition(
                query=str(conditions.get("query", "")).strip(),
                statuses=_tuple_of_strings(conditions.get("statuses")),
                media_types=_tuple_of_strings(conditions.get("media_types")),
                categories=_tuple_of_strings(conditions.get("categories")),
                review_buckets=_tuple_of_strings(conditions.get("review_buckets")),
                min_confidence=_optional_float(conditions.get("min_confidence")),
                max_confidence=_optional_float(conditions.get("max_confidence")),
                has_conflict=_optional_bool(conditions.get("has_conflict")),
                ignore_state=_optional_bool(conditions.get("ignore_state")),
            ),
            actions=ReviewRuleAction(
                set_category=_optional_string(actions.get("set_category")),
                set_ignore=_optional_bool(actions.get("set_ignore")),
                target_pattern=_optional_string(actions.get("target_pattern")),
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "scope": self.scope,
            "description": self.description,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "conditions": {
                "query": self.conditions.query,
                "statuses": list(self.conditions.statuses),
                "media_types": list(self.conditions.media_types),
                "categories": list(self.conditions.categories),
                "review_buckets": list(self.conditions.review_buckets),
                "min_confidence": self.conditions.min_confidence,
                "max_confidence": self.conditions.max_confidence,
                "has_conflict": self.conditions.has_conflict,
                "ignore_state": self.conditions.ignore_state,
            },
            "actions": {
                "set_category": self.actions.set_category,
                "set_ignore": self.actions.set_ignore,
                "target_pattern": self.actions.target_pattern,
            },
        }


@dataclass(frozen=True)
class RulePreview:
    matched_row_ids: tuple[str, ...] = ()
    patch_preview: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def rule_matches(rule: ReviewRule, row: Mapping[str, Any]) -> bool:
    title = _row_title(row)
    category = _row_category(row)
    target_path = _row_target_path(row)
    haystack = " ".join(
        [
            _row_file_name(row),
            title,
            category,
            str(row.get("error_code", "") or ""),
            target_path,
        ]
    ).lower()
    confidence = _optional_float(row.get("confidence")) or 0.0
    if rule.conditions.query and rule.conditions.query.lower() not in haystack:
        return False
    if rule.conditions.statuses and str(row.get("status", "") or "") not in rule.conditions.statuses:
        return False
    if rule.conditions.media_types and str(row.get("media_type", "") or "") not in rule.conditions.media_types:
        return False
    if rule.conditions.categories and category not in rule.conditions.categories:
        return False
    if rule.conditions.review_buckets and str(row.get("review_bucket", "") or "") not in rule.conditions.review_buckets:
        return False
    if rule.conditions.min_confidence is not None and confidence < rule.conditions.min_confidence:
        return False
    if rule.conditions.max_confidence is not None and confidence > rule.conditions.max_confidence:
        return False
    if rule.conditions.has_conflict is not None and bool(row.get("has_conflict", False)) != rule.conditions.has_conflict:
        return False
    if rule.conditions.ignore_state is not None and bool(row.get("ignore", False)) != rule.conditions.ignore_state:
        return False
    return True


def build_overlay_patch(rule: ReviewRule, row: Mapping[str, Any]) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    ai_patch: Dict[str, Any] = {}
    if rule.actions.set_category:
        ai_patch["category"] = rule.actions.set_category
    if rule.actions.set_ignore is not None:
        patch["ignore"] = rule.actions.set_ignore
    if rule.actions.target_pattern:
        patch["new_path"] = render_target_pattern(rule.actions.target_pattern, row)
    if ai_patch:
        patch["ai"] = ai_patch
    return patch


def preview_rule(rule: ReviewRule, rows: Iterable[Mapping[str, Any]]) -> RulePreview:
    matched: List[str] = []
    patch_preview: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not rule_matches(rule, row):
            continue
        row_id = str(row.get("id", row.get("row_id", "")) or "")
        if not row_id:
            continue
        matched.append(row_id)
        patch = build_overlay_patch(rule, row)
        if patch:
            patch_preview[row_id] = patch
    return RulePreview(matched_row_ids=tuple(matched), patch_preview=patch_preview)


def render_target_pattern(pattern: str, row: Mapping[str, Any]) -> str:
    metadata = row.get("metadata", {})
    meta = metadata if isinstance(metadata, dict) else {}
    title = _row_title(row) or "untitled"
    category = _row_category(row) or "other"
    file_name = _row_file_name(row)
    stem = Path(file_name).stem or "item"
    ext = Path(file_name).suffix
    hash8 = str(row.get("id", "") or row.get("hash8", "") or stem)[-8:]
    date_value = str(meta.get("exif_datetime", "") or meta.get("file_mtime", "") or "")[:10]
    date_value = date_value or "undated"
    rendered = (
        pattern.replace("{date}", date_value)
        .replace("{category}", category)
        .replace("{title}", title)
        .replace("{hash8}", hash8)
        .replace("{stem}", stem)
        .replace("{ext}", ext)
    )
    return rendered.strip()


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _row_ai_payload(row: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = row.get("ai", {})
    return payload if isinstance(payload, Mapping) else {}


def _row_title(row: Mapping[str, Any]) -> str:
    direct = str(row.get("title", "") or "").strip()
    if direct:
        return direct
    return str(_row_ai_payload(row).get("title", "") or "").strip()


def _row_category(row: Mapping[str, Any]) -> str:
    direct = str(row.get("category", "") or "").strip()
    if direct:
        return direct
    return str(_row_ai_payload(row).get("category", "") or "").strip()


def _row_file_name(row: Mapping[str, Any]) -> str:
    direct = str(row.get("file_name", "") or "").strip()
    if direct:
        return direct
    original_path = str(row.get("original_path", "") or row.get("path", "") or "").strip()
    return Path(original_path).name or "item"


def _row_target_path(row: Mapping[str, Any]) -> str:
    return str(row.get("target_suggestion", "") or row.get("new_path", "") or "").strip()
