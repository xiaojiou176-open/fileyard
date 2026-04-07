from __future__ import annotations

from packages.application.review_rules import apply_rule_to_overlay, preview_rules
from packages.domain.review_rules import ReviewRule, build_overlay_patch, preview_rule


def test_preview_rule_matches_and_builds_overlay_patch() -> None:
    rule = ReviewRule.from_dict(
        {
            "id": "rule-1",
            "name": "Travel low confidence",
            "scope": "manifest",
            "conditions": {"media_types": ["image"], "max_confidence": 0.8},
            "actions": {"set_category": "旅行", "target_pattern": "{category}/{title}__{hash8}"},
        }
    )
    rows = [
        {"id": "0", "file_name": "a.png", "media_type": "image", "title": "Trip", "category": "其他", "confidence": 0.55},
        {"id": "1", "file_name": "b.png", "media_type": "image", "title": "Other", "category": "工作", "confidence": 0.95},
    ]
    preview = preview_rule(rule, rows)
    assert preview.matched_row_ids == ("0",)
    assert preview.patch_preview["0"]["ai"]["category"] == "旅行"
    assert "Trip" in preview.patch_preview["0"]["new_path"]
    assert build_overlay_patch(rule, rows[0])["ai"]["category"] == "旅行"


def test_rule_matches_supports_optional_fields_and_wrapper_helpers() -> None:
    rule = ReviewRule.from_dict(
        {
            "id": "rule-2",
            "name": "Conflict ignore",
            "scope": "manifest",
            "conditions": {"statuses": ["pending"], "review_buckets": ["needs_review"], "has_conflict": True, "ignore_state": False},
            "actions": {"set_ignore": True},
        }
    )
    rows = [
        {"id": "10", "status": "pending", "review_bucket": "needs_review", "has_conflict": True, "ignore": False},
        {"id": "", "status": "pending", "review_bucket": "needs_review", "has_conflict": True, "ignore": False},
    ]
    preview = preview_rule(rule, rows)
    assert preview.matched_row_ids == ("10",)
    assert preview.patch_preview["10"]["ignore"] is True
    wrapper_preview = preview_rules(rule, rows)
    assert wrapper_preview["matched_count"] == 1
    assert apply_rule_to_overlay(rule, rows) == {"10": {"ignore": True}}


def test_review_rule_serialization_and_target_pattern_helpers() -> None:
    rule = ReviewRule.from_dict(
        {
            "id": "rule-3",
            "name": "Doc title",
            "scope": "",
            "conditions": {
                "query": "invoice",
                "statuses": ["pending"],
                "media_types": ["pdf"],
                "categories": ["文档"],
                "review_buckets": ["needs_review"],
                "min_confidence": 0.1,
                "max_confidence": 0.9,
                "has_conflict": "true",
                "ignore_state": "false",
            },
            "actions": {"set_category": "文档", "target_pattern": "{date}/{stem}{ext}"},
        }
    )
    serialized = rule.to_dict()
    assert serialized["scope"] == "manifest"
    assert serialized["conditions"]["has_conflict"] is True
    assert serialized["conditions"]["ignore_state"] is False
    assert build_overlay_patch(
        rule,
        {
            "id": "abcdef1234",
            "file_name": "invoice.pdf",
            "title": "invoice march",
            "category": "文档",
            "metadata": {"file_mtime": "2026-03-29T00:00:00"},
            "review_bucket": "needs_review",
            "media_type": "pdf",
            "has_conflict": True,
            "ignore": False,
            "confidence": 0.5,
        },
    )["new_path"].startswith("2026-03-29/invoice")


def test_review_rule_helpers_handle_unmatched_and_invalid_optionals() -> None:
    rule = ReviewRule.from_dict(
        {
            "id": "rule-4",
            "name": "Audio rule",
            "scope": "manifest",
            "conditions": {"media_types": ["audio"], "min_confidence": "bad", "max_confidence": ""},
            "actions": {"set_category": "", "set_ignore": "unknown", "target_pattern": ""},
        }
    )
    rows = [{"id": "a1", "media_type": "image", "title": "x", "category": "其他", "confidence": 0.2}]
    preview = preview_rule(rule, rows)
    assert preview.matched_row_ids == ()
    assert preview.patch_preview == {}
    assert rule.to_dict()["actions"]["set_category"] is None
