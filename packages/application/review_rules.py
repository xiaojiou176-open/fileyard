from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping

from packages.domain.review_rules import ReviewRule, preview_rule


def preview_rules(rule: ReviewRule, rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    preview = preview_rule(rule, rows)
    return {
        "matched_row_ids": list(preview.matched_row_ids),
        "matched_count": len(preview.matched_row_ids),
        "patch_preview": preview.patch_preview,
    }


def apply_rule_to_overlay(rule: ReviewRule, rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    preview = preview_rule(rule, rows)
    overlay_rows: Dict[str, Dict[str, Any]] = {}
    for row_id, patch in preview.patch_preview.items():
        overlay_rows[row_id] = dict(patch)
    return overlay_rows


def build_rule_draft_from_examples(
    rows: Iterable[Mapping[str, Any]],
    *,
    name: str | None = None,
) -> Dict[str, Any]:
    sample_rows = [dict(row) for row in rows]
    if len(sample_rows) < 2:
        raise ValueError("at least 2 examples are required")
    if len(sample_rows) > 5:
        raise ValueError("at most 5 examples are allowed in v1")

    media_types = {str(row.get("media_type", "") or "") for row in sample_rows}
    review_buckets = {str(row.get("review_bucket", "") or "") for row in sample_rows if str(row.get("review_bucket", "") or "")}
    categories = [category for row in sample_rows if (category := _row_category(row))]
    ignores = {bool(row.get("ignore", False)) for row in sample_rows}

    warnings: List[str] = []
    conditions: Dict[str, Any] = {
        "query": _shared_query_token(sample_rows),
        "statuses": [],
        "media_types": sorted(item for item in media_types if item) if len(media_types) == 1 else [],
        "categories": [],
        "review_buckets": sorted(review_buckets) if len(review_buckets) == 1 else [],
    }
    actions: Dict[str, Any] = {}

    category_mode = _mode_value(categories)
    if category_mode:
        actions["set_category"] = category_mode
        if len(set(categories)) > 1:
            warnings.append("Examples do not agree perfectly on category, so the draft uses the most common category.")

    if len(ignores) == 1 and True in ignores:
        actions["set_ignore"] = True

    if not actions:
        raise ValueError("examples need at least one shared outcome, such as a common category or ignore decision")

    if len(media_types) > 1:
        warnings.append("Examples span multiple media types, so the draft leaves media_types open for manual review.")
    if len(review_buckets) > 1:
        warnings.append("Examples span multiple review buckets, so the draft leaves review_buckets open for manual review.")
    if not conditions["query"]:
        warnings.append("No stable shared keyword was inferred, so the draft relies on other shared conditions.")

    draft_name = (name or f"Draft from {len(sample_rows)} examples").strip()
    description = (
        f"Generated from {len(sample_rows)} reviewed examples. Review the inferred conditions before saving or applying the draft."
    )
    example_row_ids = [str(row.get("row_id", row.get("id", "")) or "") for row in sample_rows]
    return {
        "name": draft_name,
        "scope": "manifest",
        "description": description,
        "version": 1,
        "mode": "draft_only",
        "draft_source": "review_examples_v1",
        "conditions": conditions,
        "actions": actions,
        "warnings": warnings,
        "example_row_ids": example_row_ids,
        "explainability": {
            "selected_count": len(sample_rows),
            "selected_row_ids": example_row_ids,
            "shared_media_types": sorted(item for item in media_types if item),
            "shared_review_buckets": sorted(review_buckets),
            "shared_query": conditions["query"],
            "inferred_actions": sorted(actions.keys()),
            "save_allowed": False,
            "apply_allowed": False,
        },
    }


def _shared_query_token(rows: Iterable[Mapping[str, Any]]) -> str:
    common: set[str] | None = None
    stopwords = {"png", "jpg", "jpeg", "image", "file", "img", "screenshot", "screen", "photo"}
    for row in rows:
        source = " ".join(
            [
                str(row.get("file_name", "") or ""),
                str(row.get("title", "") or ""),
                str(dict(row.get("ai", {}) or {}).get("title", "") or ""),
                str(row.get("collection_title", "") or ""),
            ]
        ).lower()
        tokens = {token for token in re.findall(r"[a-z0-9]{3,}", source) if token not in stopwords}
        common = tokens if common is None else common & tokens
        if not common:
            return ""
    return max(common, key=len) if common else ""


def _mode_value(values: List[str]) -> str:
    if not values:
        return ""
    counter = Counter(values)
    return counter.most_common(1)[0][0]


def _row_category(row: Mapping[str, Any]) -> str:
    direct = str(row.get("category", "") or "").strip()
    if direct:
        return direct
    ai = row.get("ai", {})
    if isinstance(ai, Mapping):
        return str(ai.get("category", "") or "").strip()
    return ""
