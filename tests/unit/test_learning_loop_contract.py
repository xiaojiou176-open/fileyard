from __future__ import annotations

from packages.application.review_learning import LearnedSuggestion, learn_category_rules, suggest_for_row


def test_learning_loop_converts_row_edits_into_workspace_local_suggestions() -> None:
    base_rows = [{"id": "0", "media_type": "image", "category": "其他"}]
    edited_rows = [{"id": "0", "media_type": "image", "category": "旅行"}]
    learned = learn_category_rules(base_rows, edited_rows, updated_at="2026-03-29T09:00:00Z")
    assert len(learned) == 1
    suggestions = suggest_for_row({"media_type": "image"}, learned)
    assert suggestions[0].suggestion_type == "category"
    assert suggestions[0].suggestion_value == "旅行"
    assert suggestions[0].source == "workspace_review_learning_v1"
    assert suggestions[0].reason.startswith("Observed 1 accepted review edit")
    assert suggestions[0].strength == "weak"
    assert suggestions[0].reuse_scope == "transient"
    assert "transient suggestion" in suggestions[0].scope_reason
    assert suggestions[0].explanation == suggestions[0].reason
    assert learned[0].explanation == learned[0].reason


def test_learning_loop_ignores_missing_ids_and_non_matching_rules() -> None:
    learned = learn_category_rules(
        base_rows=[{"id": "0", "media_type": "image", "category": "其他"}],
        edited_rows=[{"id": "", "media_type": "image", "category": "旅行"}, {"id": "0", "media_type": "image", "category": "其他"}],
        updated_at="2026-03-29T09:00:00Z",
    )
    assert learned == []
    assert suggest_for_row({"media_type": "audio"}, learned) == []


def test_learning_suggestion_to_dict_and_sorting() -> None:
    suggestion = LearnedSuggestion(
        signal_key="media_type",
        signal_value="image",
        suggestion_type="category",
        suggestion_value="旅行",
        confidence=0.9,
        count=5,
        confidence_label="high",
        strength="strong",
        reuse_scope="reusable",
        source="workspace_review_learning_v1",
        reason="Observed 5 accepted review edit(s) mapping media_type=image to 旅行.",
        explanation="Observed 5 accepted review edit(s) mapping media_type=image to 旅行.",
        scope_reason="Reusable because the same correction was accepted multiple times.",
    )
    assert suggestion.to_dict()["suggestion_value"] == "旅行"

    learned = learn_category_rules(
        base_rows=[{"id": "0", "media_type": "image", "category": "其他"}, {"id": "1", "media_type": "image", "category": "其他"}],
        edited_rows=[{"id": "0", "media_type": "image", "category": "旅行"}, {"id": "1", "media_type": "image", "category": "旅行"}],
        updated_at="2026-03-29T09:00:00Z",
    )
    suggestions = suggest_for_row({"media_type": "image"}, learned)
    assert suggestions[0].count == 2
    assert suggestions[0].confidence_label in {"medium", "high"}
    assert suggestions[0].strength in {"medium", "strong"}
    assert suggestions[0].reuse_scope == "reusable"
    assert "reusable workspace preference" in suggestions[0].scope_reason
