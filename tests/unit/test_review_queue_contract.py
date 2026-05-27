from __future__ import annotations

from packages.domain.review_queue import (
    REVIEW_BUCKET_AUTO_SAFE,
    REVIEW_BUCKET_BLOCKED,
    REVIEW_BUCKET_CONFLICT,
    REVIEW_BUCKET_NEEDS_REVIEW,
    build_review_queue_summary,
    classify_review_bucket,
    evaluate_review_bucket,
)


def test_classify_review_bucket_respects_error_and_conflict_priority() -> None:
    assert classify_review_bucket({"status": "error", "error_code": ""}) == REVIEW_BUCKET_BLOCKED
    assert classify_review_bucket({"status": "pending", "error_code": "HASH_FAIL"}) == REVIEW_BUCKET_BLOCKED
    assert classify_review_bucket({"status": "duplicate", "error_code": ""}) == REVIEW_BUCKET_CONFLICT
    assert classify_review_bucket({"status": "pending", "error_code": ""}, conflict_open=True) == REVIEW_BUCKET_CONFLICT


def test_classify_review_bucket_routes_low_confidence_and_edited_rows_to_needs_review() -> None:
    assert classify_review_bucket({"status": "pending", "error_code": "", "confidence": 0.4}) == REVIEW_BUCKET_NEEDS_REVIEW
    assert classify_review_bucket({"status": "pending", "error_code": "", "confidence": 0.95}, edited=True) == REVIEW_BUCKET_NEEDS_REVIEW
    assert classify_review_bucket({"status": "pending", "error_code": "", "confidence": 0.95}) == REVIEW_BUCKET_AUTO_SAFE


def test_build_review_queue_summary_counts_buckets() -> None:
    payload = build_review_queue_summary(
        [
            {"review_bucket": REVIEW_BUCKET_AUTO_SAFE},
            {"review_bucket": REVIEW_BUCKET_NEEDS_REVIEW},
            {"review_bucket": REVIEW_BUCKET_CONFLICT},
            {"review_bucket": REVIEW_BUCKET_BLOCKED},
        ]
    ).to_dict()
    assert payload == {
        "total": 4,
        "auto_safe": 1,
        "needs_review": 1,
        "conflict": 1,
        "blocked": 1,
    }


def test_review_queue_routes_ignore_collection_uncertainty_and_learning_to_needs_review() -> None:
    assert classify_review_bucket({"status": "pending", "error_code": "", "confidence": 0.95, "ignore": True}) == REVIEW_BUCKET_NEEDS_REVIEW
    assert (
        classify_review_bucket({"status": "pending", "error_code": "", "confidence": 0.95}, collection_uncertain=True)
        == REVIEW_BUCKET_NEEDS_REVIEW
    )
    assert (
        classify_review_bucket({"status": "pending", "error_code": "", "confidence": 0.95}, learned_suggestion_count=2)
        == REVIEW_BUCKET_NEEDS_REVIEW
    )


def test_evaluate_review_bucket_returns_explainability_reasons() -> None:
    decision = evaluate_review_bucket(
        {"status": "pending", "error_code": "", "confidence": 0.42, "ignore": True},
        edited=True,
        collection_uncertain=True,
        learned_suggestion_count=1,
    )
    assert decision.bucket == REVIEW_BUCKET_NEEDS_REVIEW
    assert "ignored_row" in decision.reason_codes
    assert "overlay_edited" in decision.reason_codes
    assert "low_confidence" in decision.reason_codes
    assert "collection_uncertain" in decision.reason_codes
    assert "learned_suggestion_present" in decision.reason_codes
