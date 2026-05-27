from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Sequence

from packages.domain.review_queue import (
    LOW_COLLECTION_CONFIDENCE_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
    REVIEW_BUCKET_BLOCKED,
    REVIEW_BUCKET_CONFLICT,
    REVIEW_BUCKET_NEEDS_REVIEW,
    build_batch_triage,
)


@dataclass(frozen=True)
class CopilotReason:
    key: str
    title: str
    count: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "count": self.count,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CopilotPriority:
    row_id: str
    file_name: str
    bucket: str
    reason: str
    suggested_action: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "file_name": self.file_name,
            "bucket": self.bucket,
            "reason": self.reason,
            "suggested_action": self.suggested_action,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class CopilotRuleOpportunity:
    key: str
    title: str
    reason: str
    row_ids: tuple[str, ...]
    suggested_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "reason": self.reason,
            "row_ids": list(self.row_ids),
            "suggested_action": self.suggested_action,
        }


@dataclass(frozen=True)
class CopilotSummary:
    mode: str
    headline: str
    reasons: tuple[CopilotReason, ...]
    priorities: tuple[CopilotPriority, ...]
    rule_opportunities: tuple[CopilotRuleOpportunity, ...]
    batch_triage: tuple[dict[str, Any], ...]
    guardrails: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "headline": self.headline,
            "reasons": [item.to_dict() for item in self.reasons],
            "priorities": [item.to_dict() for item in self.priorities],
            "rule_opportunities": [item.to_dict() for item in self.rule_opportunities],
            "batch_triage": [dict(item) for item in self.batch_triage],
            "guardrails": dict(self.guardrails),
        }


def build_review_copilot_summary(
    rows: Iterable[Mapping[str, Any]],
    collections: Iterable[Mapping[str, Any]],
) -> CopilotSummary:
    row_list: Sequence[Mapping[str, Any]] = [dict(row) for row in rows]
    collection_list: Sequence[Mapping[str, Any]] = [dict(item) for item in collections]

    blocked = [row for row in row_list if str(row.get("review_bucket", "")) == REVIEW_BUCKET_BLOCKED]
    conflicts = [row for row in row_list if str(row.get("review_bucket", "")) == REVIEW_BUCKET_CONFLICT]
    review_rows = [row for row in row_list if str(row.get("review_bucket", "")) == REVIEW_BUCKET_NEEDS_REVIEW]
    low_confidence = [row for row in review_rows if _safe_float(row.get("confidence")) < LOW_CONFIDENCE_THRESHOLD]
    learned_rows = [row for row in review_rows if row.get("learned_suggestions")]
    collection_uncertain = [
        row for row in review_rows if _safe_float(row.get("collection_confidence")) < LOW_COLLECTION_CONFIDENCE_THRESHOLD
    ]

    reasons: List[CopilotReason] = []
    if blocked:
        reasons.append(
            CopilotReason(
                key="blocked",
                title="Blocked rows need a human fix first",
                count=len(blocked),
                detail="These rows already carry an error code or a blocking status, so they should be cleared before dry-run apply.",
            )
        )
    if conflicts:
        reasons.append(
            CopilotReason(
                key="conflicts",
                title="Conflicts still need a decision",
                count=len(conflicts),
                detail="These rows point at competing targets or duplicate outcomes and should be resolved before execution.",
            )
        )
    if low_confidence:
        reasons.append(
            CopilotReason(
                key="low_confidence",
                title="Low-confidence rows are driving the review queue",
                count=len(low_confidence),
                detail=f"Fileorganize currently sends rows below {int(LOW_CONFIDENCE_THRESHOLD * 100)}% confidence into manual review.",
            )
        )
    if learned_rows:
        reasons.append(
            CopilotReason(
                key="learned_suggestions",
                title="Some rows already have learned suggestions",
                count=len(learned_rows),
                detail="These are the fastest rows to inspect, because the workspace already has a repeatable hint to explain.",
            )
        )
    if collection_uncertain:
        reasons.append(
            CopilotReason(
                key="collection_uncertain",
                title="Some inferred collections still look weak",
                count=len(collection_uncertain),
                detail=(
                    f"Rows below {int(LOW_COLLECTION_CONFIDENCE_THRESHOLD * 100)}% "
                    "collection confidence stay in review until a human confirms the grouping."
                ),
            )
        )

    priorities = _build_priorities(row_list)
    opportunities = _build_rule_opportunities(review_rows, collection_list)
    batch_triage = tuple(build_batch_triage(row_list, collection_list))

    headline_parts: List[str] = []
    if blocked:
        headline_parts.append(f"{len(blocked)} blocked")
    if conflicts:
        headline_parts.append(f"{len(conflicts)} conflicts")
    if review_rows:
        headline_parts.append(f"{len(review_rows)} human-review rows")
    if opportunities:
        headline_parts.append(f"{len(opportunities)} rule opportunity{'ies' if len(opportunities) != 1 else ''}")
    headline = "Review Copilot found " + ", ".join(headline_parts) if headline_parts else "This batch is ready for a quick review pass."

    return CopilotSummary(
        mode="deterministic-review-summary",
        headline=headline,
        reasons=tuple(reasons),
        priorities=tuple(priorities),
        rule_opportunities=tuple(opportunities),
        batch_triage=batch_triage,
        guardrails={
            "review_only": True,
            "draft_only": True,
            "overlay_only": True,
            "execute_allowed": False,
            "auto_apply": False,
            "allowed_routes": [
                "/api/jobs/{job_id}/review-rules/preview",
                "/api/jobs/{job_id}/review-rules/apply",
                "/api/jobs/{job_id}/review-rules/from-examples",
                "/api/jobs/{job_id}/review-queue/batch-triage",
            ],
        },
    )


def _build_priorities(rows: Sequence[Mapping[str, Any]]) -> List[CopilotPriority]:
    bucket_rank = {
        REVIEW_BUCKET_BLOCKED: 0,
        REVIEW_BUCKET_CONFLICT: 1,
        REVIEW_BUCKET_NEEDS_REVIEW: 2,
    }

    def sort_key(row: Mapping[str, Any]) -> tuple[int, float, int]:
        bucket = str(row.get("review_bucket", "") or REVIEW_BUCKET_NEEDS_REVIEW)
        confidence = _safe_float(row.get("confidence"))
        learned_count = len(list(row.get("learned_suggestions") or []))
        return (bucket_rank.get(bucket, 3), confidence, -learned_count)

    priorities: List[CopilotPriority] = []
    for row in sorted(rows, key=sort_key)[:5]:
        row_id = str(row.get("row_id", row.get("id", "")) or "")
        bucket = str(row.get("review_bucket", REVIEW_BUCKET_NEEDS_REVIEW) or REVIEW_BUCKET_NEEDS_REVIEW)
        priorities.append(
            CopilotPriority(
                row_id=row_id,
                file_name=_row_file_name(row),
                bucket=bucket,
                reason=_priority_reason(row),
                suggested_action=_priority_action(row),
                confidence=_safe_float(row.get("confidence")),
            )
        )
    return priorities


def _priority_reason(row: Mapping[str, Any]) -> str:
    if str(row.get("review_bucket", "")) == REVIEW_BUCKET_BLOCKED:
        error_code = str(row.get("error_code", "") or "unknown_error")
        return f"Blocked by error code {error_code}."
    if str(row.get("review_bucket", "")) == REVIEW_BUCKET_CONFLICT:
        return "Conflict resolution is required before dry-run apply."
    if row.get("learned_suggestions"):
        return "A learned suggestion already exists for this row."
    if _safe_float(row.get("confidence")) < LOW_CONFIDENCE_THRESHOLD:
        return "Model confidence is below the review threshold."
    if _safe_float(row.get("collection_confidence")) < LOW_COLLECTION_CONFIDENCE_THRESHOLD:
        return "Collection confidence is still weak."
    return "This row still needs a human pass before apply."


def _priority_action(row: Mapping[str, Any]) -> str:
    if str(row.get("review_bucket", "")) == REVIEW_BUCKET_BLOCKED:
        return "Inspect the blocking error first."
    if str(row.get("review_bucket", "")) == REVIEW_BUCKET_CONFLICT:
        return "Resolve the conflict or open the Manifest Workbench."
    if row.get("learned_suggestions"):
        return "Review the suggestion and either apply it or promote it into a rule draft."
    return "Review the row and decide whether it belongs in a batch action."


def _build_rule_opportunities(
    rows: Sequence[Mapping[str, Any]],
    collections: Sequence[Mapping[str, Any]],
) -> List[CopilotRuleOpportunity]:
    collection_map = {str(item.get("id", "")): item for item in collections if str(item.get("id", ""))}
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in rows:
        suggestions = row.get("learned_suggestions") or []
        top_suggestion = suggestions[0] if suggestions else None
        if not isinstance(top_suggestion, Mapping):
            continue
        suggestion_type = str(top_suggestion.get("suggestion_type", "") or "")
        suggestion_value = str(top_suggestion.get("suggestion_value", "") or "")
        media_type = str(row.get("media_type", "") or "unknown")
        if suggestion_type != "category" or not suggestion_value:
            continue
        row_id = str(row.get("row_id", row.get("id", "")) or "")
        if not row_id:
            continue
        groups[(media_type, suggestion_type, suggestion_value)].append(row_id)

    opportunities: List[CopilotRuleOpportunity] = []
    for (media_type, _, suggestion_value), suggestion_row_ids in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0][2]))[:3]:
        if len(suggestion_row_ids) < 2:
            continue
        title = f"{len(suggestion_row_ids)} {media_type} rows all lean toward “{suggestion_value}”"
        reason = (
            "The workspace already repeats the same learned category hint across these rows, "
            "which makes them good candidates for a draft rule."
        )
        opportunities.append(
            CopilotRuleOpportunity(
                key=f"{media_type}:{suggestion_value}",
                title=title,
                reason=reason,
                row_ids=tuple(suggestion_row_ids[:5]),
                suggested_action="Create a draft rule from these examples.",
            )
        )

    if not opportunities and collection_map:
        for collection_id, collection in collection_map.items():
            collection_row_ids = tuple(str(item) for item in collection.get("row_ids", []) if str(item))
            if len(collection_row_ids) < 2:
                continue
            opportunities.append(
                CopilotRuleOpportunity(
                    key=f"collection:{collection_id}",
                    title=f"Collection “{collection.get('title', 'Untitled collection')}” could be triaged together",
                    reason=str(collection.get("reason", "") or "These rows already travel as the same inferred collection."),
                    row_ids=tuple(collection_row_ids[:5]),
                    suggested_action="Use the collection as a rule-from-examples starting set.",
                )
            )
            break
    return opportunities


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _row_file_name(row: Mapping[str, Any]) -> str:
    direct = str(row.get("file_name", "") or "").strip()
    if direct:
        return direct
    original_path = str(row.get("original_path", "") or row.get("path", "") or "").strip()
    if original_path:
        return original_path.split("/")[-1] or "Untitled row"
    ai_payload = row.get("ai", {})
    if isinstance(ai_payload, Mapping):
        title = str(ai_payload.get("title", "") or "").strip()
        if title:
            return title
    return "Untitled row"
