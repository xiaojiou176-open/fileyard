from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

REVIEW_BUCKET_AUTO_SAFE = "auto_safe"
REVIEW_BUCKET_NEEDS_REVIEW = "needs_review"
REVIEW_BUCKET_CONFLICT = "conflict"
REVIEW_BUCKET_BLOCKED = "blocked"

LOW_CONFIDENCE_THRESHOLD = 0.8
LOW_COLLECTION_CONFIDENCE_THRESHOLD = 0.85
MAX_COPILOT_REASON_ITEMS = 5
MAX_BATCH_TRIAGE_ITEMS = 5

REVIEW_BUCKET_PRIORITY = {
    REVIEW_BUCKET_AUTO_SAFE: 0,
    REVIEW_BUCKET_NEEDS_REVIEW: 1,
    REVIEW_BUCKET_CONFLICT: 2,
    REVIEW_BUCKET_BLOCKED: 3,
}

REASON_LABELS = {
    "status_error": "row has error status or error_code",
    "duplicate_conflict": "row still has duplicate/conflict risk",
    "ignored_row": "row is explicitly marked ignore and still needs confirmation",
    "overlay_edited": "row has local overlay edits that should be reviewed before execution",
    "low_confidence": "row confidence is below the review threshold",
    "collection_uncertain": "collection grouping is not confident enough for auto-safe",
    "learned_suggestion_present": "workspace learning has suggestions that still need human confirmation",
    "auto_safe_clear": "no review trigger fired; row is currently auto-safe",
}


@dataclass(frozen=True)
class ReviewQueueSummary:
    total: int
    auto_safe: int
    needs_review: int
    conflict: int
    blocked: int

    def to_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            REVIEW_BUCKET_AUTO_SAFE: self.auto_safe,
            REVIEW_BUCKET_NEEDS_REVIEW: self.needs_review,
            REVIEW_BUCKET_CONFLICT: self.conflict,
            REVIEW_BUCKET_BLOCKED: self.blocked,
        }


@dataclass(frozen=True)
class ReviewBucketDecision:
    bucket: str
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
        }


def evaluate_review_bucket(
    row: Mapping[str, Any],
    *,
    conflict_open: bool = False,
    edited: bool = False,
    collection_uncertain: bool = False,
    learned_suggestion_count: int = 0,
) -> ReviewBucketDecision:
    status = str(row.get("status", "") or "")
    error_code = str(row.get("error_code", "") or "")
    ignore = bool(row.get("ignore", False))
    confidence = _safe_float(row.get("confidence", 0))

    bucket = REVIEW_BUCKET_AUTO_SAFE
    reason_codes: list[str] = []
    reasons: list[str] = []

    if status == "error" or error_code:
        bucket = _higher_priority_bucket(bucket, REVIEW_BUCKET_BLOCKED)
        reason_codes.append("status_error")
        reasons.append(REASON_LABELS["status_error"])
    if conflict_open or status == "duplicate":
        bucket = _higher_priority_bucket(bucket, REVIEW_BUCKET_CONFLICT)
        reason_codes.append("duplicate_conflict")
        reasons.append(REASON_LABELS["duplicate_conflict"])
    if ignore:
        bucket = _higher_priority_bucket(bucket, REVIEW_BUCKET_NEEDS_REVIEW)
        reason_codes.append("ignored_row")
        reasons.append(REASON_LABELS["ignored_row"])
    if edited:
        bucket = _higher_priority_bucket(bucket, REVIEW_BUCKET_NEEDS_REVIEW)
        reason_codes.append("overlay_edited")
        reasons.append(REASON_LABELS["overlay_edited"])
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        bucket = _higher_priority_bucket(bucket, REVIEW_BUCKET_NEEDS_REVIEW)
        reason_codes.append("low_confidence")
        reasons.append(REASON_LABELS["low_confidence"])
    if collection_uncertain:
        bucket = _higher_priority_bucket(bucket, REVIEW_BUCKET_NEEDS_REVIEW)
        reason_codes.append("collection_uncertain")
        reasons.append(REASON_LABELS["collection_uncertain"])
    if learned_suggestion_count > 0:
        bucket = _higher_priority_bucket(bucket, REVIEW_BUCKET_NEEDS_REVIEW)
        reason_codes.append("learned_suggestion_present")
        reasons.append(REASON_LABELS["learned_suggestion_present"])

    if not reason_codes:
        reason_codes.append("auto_safe_clear")
        reasons.append(REASON_LABELS["auto_safe_clear"])
    return ReviewBucketDecision(bucket=bucket, reason_codes=tuple(reason_codes), reasons=tuple(reasons))


def classify_review_bucket(
    row: Mapping[str, Any],
    *,
    conflict_open: bool = False,
    edited: bool = False,
    collection_uncertain: bool = False,
    learned_suggestion_count: int = 0,
) -> str:
    return evaluate_review_bucket(
        row,
        conflict_open=conflict_open,
        edited=edited,
        collection_uncertain=collection_uncertain,
        learned_suggestion_count=learned_suggestion_count,
    ).bucket


def build_review_queue_summary(rows: Iterable[Mapping[str, Any]]) -> ReviewQueueSummary:
    counter: Counter[str] = Counter()
    total = 0
    for row in rows:
        total += 1
        counter[str(row.get("review_bucket", REVIEW_BUCKET_NEEDS_REVIEW))] += 1
    return ReviewQueueSummary(
        total=total,
        auto_safe=counter[REVIEW_BUCKET_AUTO_SAFE],
        needs_review=counter[REVIEW_BUCKET_NEEDS_REVIEW],
        conflict=counter[REVIEW_BUCKET_CONFLICT],
        blocked=counter[REVIEW_BUCKET_BLOCKED],
    )


def build_batch_triage(rows: Sequence[Mapping[str, Any]], collections: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    row_map = {str(row.get("row_id", row.get("id", "")) or ""): row for row in rows}
    batches: list[dict[str, Any]] = []

    for bucket in (REVIEW_BUCKET_BLOCKED, REVIEW_BUCKET_CONFLICT, REVIEW_BUCKET_NEEDS_REVIEW):
        bucket_row_ids = [
            str(row.get("row_id", row.get("id", "")) or "")
            for row in rows
            if str(row.get("review_bucket", "")) == bucket and str(row.get("row_id", row.get("id", "")) or "")
        ]
        if len(bucket_row_ids) >= 2:
            batches.append(
                {
                    "id": f"bucket:{bucket}",
                    "kind": "bucket",
                    "label": f"{bucket} batch",
                    "review_bucket": bucket,
                    "count": len(bucket_row_ids),
                    "row_ids": bucket_row_ids,
                    "reason": f"{len(bucket_row_ids)} rows currently share the {bucket} review state",
                    "next_step": _build_batch_next_step([row_map[row_id] for row_id in bucket_row_ids if row_id in row_map], bucket),
                }
            )

    for collection in collections:
        collection_id = str(collection.get("id", "") or "")
        collection_row_ids = [str(item) for item in collection.get("row_ids", []) if str(item)]
        members = [row_map[row_id] for row_id in collection_row_ids if row_id in row_map]
        review_members = [row for row in members if str(row.get("review_bucket", "")) != REVIEW_BUCKET_AUTO_SAFE]
        if len(review_members) < 2:
            continue
        bucket = _highest_priority_bucket(str(row.get("review_bucket", REVIEW_BUCKET_NEEDS_REVIEW)) for row in review_members)
        member_row_ids = [str(row.get("row_id", row.get("id", "")) or "") for row in review_members]
        batches.append(
            {
                "id": f"collection:{collection_id}",
                "kind": "collection",
                "label": str(collection.get("title", "") or collection_id),
                "review_bucket": bucket,
                "collection_id": collection_id,
                "count": len(member_row_ids),
                "row_ids": member_row_ids,
                "reason": str(collection.get("reason", "") or "collection requires grouped review"),
                "next_step": str(collection.get("next_step", "") or _build_batch_next_step(review_members, bucket)),
            }
        )

    batches.sort(
        key=lambda item: (
            -REVIEW_BUCKET_PRIORITY.get(str(item.get("review_bucket", "")), 0),
            -int(item.get("count", 0)),
            str(item.get("label", "")),
        )
    )
    return batches[:MAX_BATCH_TRIAGE_ITEMS]


def build_review_copilot_summary(
    rows: Sequence[Mapping[str, Any]],
    collections: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    queue_summary = build_review_queue_summary(rows).to_dict()
    reason_counter: Counter[str] = Counter()
    for row in rows:
        explainability = row.get("review_explainability", {})
        if isinstance(explainability, Mapping):
            for code in explainability.get("reason_codes", []) or []:
                reason_counter[str(code)] += 1

    prioritized_reasons = [
        {
            "code": code,
            "label": REASON_LABELS.get(code, code),
            "count": count,
        }
        for code, count in reason_counter.most_common(MAX_COPILOT_REASON_ITEMS)
    ]
    batches = build_batch_triage(rows, collections)
    blocked = int(queue_summary.get(REVIEW_BUCKET_BLOCKED, 0))
    conflicts = int(queue_summary.get(REVIEW_BUCKET_CONFLICT, 0))
    needs_review = int(queue_summary.get(REVIEW_BUCKET_NEEDS_REVIEW, 0))
    headline = "Queue is ready for auto-safe flow."
    if blocked:
        headline = f"{blocked} blocked rows should be resolved before any downstream action."
    elif conflicts:
        headline = f"{conflicts} conflict rows need path resolution before the queue can settle."
    elif needs_review:
        headline = f"{needs_review} rows need human review before they should move toward apply."

    return {
        "version": "v1",
        "mode": "deterministic",
        "headline": headline,
        "summary": queue_summary,
        "top_reasons": prioritized_reasons,
        "batch_triage": batches,
        "guardrails": {
            "review_only": True,
            "auto_apply": False,
            "allowed_routes": ["manifest_overlay_batch", "review_rules_preview"],
        },
    }


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _higher_priority_bucket(current: str, candidate: str) -> str:
    if REVIEW_BUCKET_PRIORITY[candidate] > REVIEW_BUCKET_PRIORITY[current]:
        return candidate
    return current


def _highest_priority_bucket(buckets: Iterable[str]) -> str:
    winner = REVIEW_BUCKET_NEEDS_REVIEW
    for bucket in buckets:
        winner = _higher_priority_bucket(winner, str(bucket or REVIEW_BUCKET_NEEDS_REVIEW))
    return winner


def _build_batch_next_step(rows: Sequence[Mapping[str, Any]], bucket: str) -> dict[str, Any]:
    rule_seed = _infer_rule_seed(rows, bucket)
    if rule_seed:
        return {
            "route": "review_rules_preview",
            "mode": "draft_rule_seed",
            "request_payload": {"rule": rule_seed},
        }
    return {
        "route": "manifest_overlay_batch",
        "mode": "review_only_overlay_batch",
        "request_payload": {"operations": []},
    }


def _infer_rule_seed(rows: Sequence[Mapping[str, Any]], bucket: str) -> dict[str, Any]:
    media_types = {str(row.get("media_type", "") or "") for row in rows if str(row.get("media_type", "") or "")}
    suggestion_counter: Counter[str] = Counter()
    for row in rows:
        for suggestion in row.get("learned_suggestions", []) or []:
            if isinstance(suggestion, Mapping) and str(suggestion.get("suggestion_type", "")) == "category":
                suggestion_counter[str(suggestion.get("suggestion_value", "") or "")] += 1
    if len(media_types) != 1 or not suggestion_counter:
        return {}
    category, match_count = suggestion_counter.most_common(1)[0]
    if not category or match_count < 2:
        return {}
    media_type = next(iter(media_types))
    return {
        "name": f"Draft {media_type} -> {category}",
        "scope": "manifest",
        "description": "Deterministic draft seed suggested by review copilot batch triage.",
        "conditions": {
            "media_types": [media_type],
            "review_buckets": [bucket],
        },
        "actions": {
            "set_category": category,
        },
    }
