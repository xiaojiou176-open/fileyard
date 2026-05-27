from __future__ import annotations

from packages.application.review_copilot import build_review_copilot_summary


def test_review_copilot_summary_surfaces_reasons_priorities_and_rule_opportunities() -> None:
    rows = [
        {
            "row_id": "0",
            "file_name": "receipt-1.png",
            "review_bucket": "blocked",
            "error_code": "HASH_FAIL",
            "confidence": 0.92,
            "learned_suggestions": [],
        },
        {
            "row_id": "1",
            "file_name": "receipt-2.png",
            "review_bucket": "needs_review",
            "confidence": 0.62,
            "media_type": "image",
            "learned_suggestions": [
                {
                    "suggestion_type": "category",
                    "suggestion_value": "票据",
                }
            ],
        },
        {
            "row_id": "2",
            "file_name": "receipt-3.png",
            "review_bucket": "needs_review",
            "confidence": 0.64,
            "media_type": "image",
            "learned_suggestions": [
                {
                    "suggestion_type": "category",
                    "suggestion_value": "票据",
                }
            ],
        },
    ]
    summary = build_review_copilot_summary(rows, [])
    payload = summary.to_dict()

    assert payload["mode"] == "deterministic-review-summary"
    assert payload["reasons"]
    assert payload["priorities"]
    assert payload["rule_opportunities"]
    assert payload["rule_opportunities"][0]["suggested_action"] == "Create a draft rule from these examples."
    assert payload["guardrails"]["review_only"] is True
    assert payload["guardrails"]["execute_allowed"] is False
    assert "/api/jobs/{job_id}/review-rules/from-examples" in payload["guardrails"]["allowed_routes"]
    assert payload["batch_triage"][0]["id"] == "bucket:needs_review"
    assert payload["batch_triage"][0]["review_bucket"] == "needs_review"
