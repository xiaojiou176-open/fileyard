#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_OUTPUT = REPO_ROOT / "contracts" / "api" / "web_api.openapi.yaml"
GENERATED_WEBUI_DIR = REPO_ROOT / "contracts" / "api" / "generated" / "webui"
ROUTE_DECORATOR_PATTERN = re.compile(r'@router\.(?P<method>get|post|patch|delete)\("(?P<path>[^"]+)"')

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _prepare_contract_env() -> None:
    temp_workspace = Path(tempfile.gettempdir()) / "fileorganize-api-contract-workspace"
    temp_workspace.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("FILEORGANIZE_WORKSPACE_ROOT", str(temp_workspace))
    os.environ.setdefault("FILEORGANIZE_INPUT_ROOT", str(temp_workspace / "data" / "raw"))
    os.environ.setdefault("FILEORGANIZE_OUTPUT_ROOT", str(temp_workspace / "data" / "organized"))
    os.environ.setdefault("FILEORGANIZE_MANIFEST_ROOT", str(temp_workspace / ".fileorganize" / "manifests"))
    os.environ.setdefault("FILEORGANIZE_ARTIFACT_ROOT", str(temp_workspace / ".fileorganize" / "artifacts"))
    os.environ.setdefault("FILEORGANIZE_RUN_BUNDLE_ROOT", str(temp_workspace / ".fileorganize" / "runs"))


def _load_openapi() -> dict[str, Any]:
    _prepare_contract_env()
    return _fallback_openapi()


def _fallback_openapi() -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    web_api_path = REPO_ROOT / "apps" / "api" / "web_api.py"
    for line in web_api_path.read_text(encoding="utf-8").splitlines():
        match = ROUTE_DECORATOR_PATTERN.search(line)
        if not match:
            continue
        method = match.group("method").lower()
        path = match.group("path")
        paths.setdefault(path, {})
        paths[path][method] = {
            "operationId": f"{method}_{path.strip('/').replace('/', '_').replace('{', '').replace('}', '') or 'root'}",
            "responses": {"200": {"description": "fallback-generated response"}},
        }
    _overlay_wave2_paths(paths)
    return {
        "openapi": "3.1.0",
        "info": {"title": "Fileorganize Web API", "version": "2.0.0"},
        "paths": paths,
        "components": {"schemas": _wave2_schemas()},
    }


def _response_ref(schema: str, *, description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {"$ref": f"#/components/schemas/{schema}"},
            }
        },
    }


def _overlay_wave2_paths(paths: dict[str, dict[str, Any]]) -> None:
    wave2_paths: dict[str, dict[str, Any]] = {
        "/api/jobs/{job_id}/review-queue": {
            "get": {
                "operationId": "get_review_queue",
                "summary": "Return review queue rows with explainability and deterministic copilot hints",
                "responses": {
                    "200": _response_ref(
                        "ReviewQueueResponse",
                        description="Review-only queue payload with deterministic guardrails and batch suggestions.",
                    )
                },
            }
        },
        "/api/jobs/{job_id}/report": {
            "get": {
                "operationId": "get_job_report",
                "summary": "Return persisted report payload enriched with Wave 2 review intelligence context",
                "responses": {
                    "200": _response_ref(
                        "JobReportResponse",
                        description="Report payload plus review intelligence summary for frontends.",
                    )
                },
            }
        },
        "/api/preferences/strategy-packs": {
            "get": {
                "operationId": "list_strategy_packs",
                "summary": "List repo-shipped strategy packs with defaults and explainability",
                "responses": {
                    "200": _response_ref(
                        "StrategyPackListResponse",
                        description="Strategy packs remain template defaults, not a plugin marketplace.",
                    )
                },
            }
        },
        "/api/preferences/learned-rules": {
            "get": {
                "operationId": "list_learned_rules",
                "summary": "List learned suggestions and clarify transient vs reusable scope",
                "responses": {
                    "200": _response_ref(
                        "LearnedRuleListResponse",
                        description="Suggestion-layer learned rules only; apply remains manual.",
                    )
                },
            }
        },
        "/api/preferences/watch-sources": {
            "get": {
                "operationId": "list_watch_sources",
                "summary": "List watch sources with strategy pack context",
                "responses": {
                    "200": _response_ref(
                        "WatchSourceListResponse",
                        description="Watch sources stay local-first and only drive discovery plus explicit analyze actions.",
                    )
                },
            }
        },
        "/api/inbox/scan": {
            "post": {
                "operationId": "scan_inbox_sources",
                "summary": "Discover inbox batches without auto-enqueueing analyze",
                "responses": {
                    "200": _response_ref(
                        "InboxScanResponse",
                        description="Discovery-only inbox response with explicit analyze action payloads.",
                    )
                },
            }
        },
        "/api/inbox/analyze": {
            "post": {
                "operationId": "start_inbox_analyze",
                "summary": "Explicitly start analyze from an inbox batch using strategy pack defaults",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/InboxAnalyzeRequest"}}},
                },
                "responses": {
                    "202": _response_ref(
                        "InboxAnalyzeResponse",
                        description="Explicit inbox analyze bridge from discovery into review-first analyze.",
                    )
                },
            }
        },
        "/api/jobs/{job_id}/review-rules/apply": {
            "post": {
                "operationId": "apply_review_rule",
                "summary": "Apply a saved or inline rule to the overlay only",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ReviewRuleApplyRequest"}}},
                },
                "responses": {
                    "200": _response_ref(
                        "ReviewRuleApplyResponse",
                        description="Overlay-only rule application result. Execution remains disallowed.",
                    )
                },
            }
        },
        "/api/jobs/{job_id}/review-rules/from-examples": {
            "post": {
                "operationId": "draft_review_rule_from_examples",
                "summary": "Infer a draft rule from reviewed examples without saving or auto-applying it",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ReviewRuleFromExamplesRequest"}}},
                },
                "responses": {
                    "200": _response_ref(
                        "ReviewRuleDraftResponse",
                        description="Draft-only response with explicit no-save and no-execute guardrails.",
                    )
                },
            }
        },
        "/api/jobs/{job_id}/review-queue/batch-triage": {
            "post": {
                "operationId": "batch_triage_review_queue",
                "summary": "Apply review queue edits to the overlay for a selected batch",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ReviewQueueBatchTriageRequest"}}},
                },
                "responses": {
                    "200": _response_ref(
                        "ReviewQueueBatchTriageResponse",
                        description="Overlay-only batch triage response. Execution remains disallowed.",
                    )
                },
            }
        },
    }
    for path, methods in wave2_paths.items():
        paths.setdefault(path, {}).update(methods)


def _wave2_schemas() -> dict[str, Any]:
    bucket_enum = ["auto_safe", "needs_review", "conflict", "blocked"]
    return {
        "ReviewExplainability": {
            "type": "object",
            "required": [
                "bucket",
                "reason_codes",
                "reasons",
                "collection_confidence",
                "learned_suggestion_count",
                "edited",
                "has_conflict",
            ],
            "properties": {
                "bucket": {"type": "string", "enum": bucket_enum},
                "reason_codes": {"type": "array", "items": {"type": "string"}},
                "reasons": {"type": "array", "items": {"type": "string"}},
                "collection_confidence": {"type": "number"},
                "learned_suggestion_count": {"type": "integer"},
                "edited": {"type": "boolean"},
                "has_conflict": {"type": "boolean"},
            },
        },
        "ReviewQueueBatchSuggestion": {
            "type": "object",
            "required": ["id", "kind", "label", "review_bucket", "count", "row_ids", "reason", "next_step"],
            "properties": {
                "id": {"type": "string"},
                "kind": {"type": "string", "enum": ["bucket", "collection"]},
                "label": {"type": "string"},
                "review_bucket": {"type": "string", "enum": bucket_enum},
                "collection_id": {"type": "string"},
                "count": {"type": "integer"},
                "row_ids": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
                "next_step": {"type": "string"},
            },
        },
        "ReviewCopilotReason": {
            "type": "object",
            "required": ["key", "title", "count", "detail"],
            "properties": {
                "key": {"type": "string"},
                "title": {"type": "string"},
                "count": {"type": "integer"},
                "detail": {"type": "string"},
            },
        },
        "ReviewCopilotPriority": {
            "type": "object",
            "required": ["row_id", "file_name", "bucket", "reason", "suggested_action", "confidence"],
            "properties": {
                "row_id": {"type": "string"},
                "file_name": {"type": "string"},
                "bucket": {"type": "string", "enum": bucket_enum},
                "reason": {"type": "string"},
                "suggested_action": {"type": "string"},
                "confidence": {"type": "number"},
            },
        },
        "ReviewCopilotRuleOpportunity": {
            "type": "object",
            "required": ["key", "title", "reason", "row_ids", "suggested_action"],
            "properties": {
                "key": {"type": "string"},
                "title": {"type": "string"},
                "reason": {"type": "string"},
                "row_ids": {"type": "array", "items": {"type": "string"}},
                "suggested_action": {"type": "string"},
            },
        },
        "ReviewCopilotGuardrails": {
            "type": "object",
            "required": ["review_only", "draft_only", "overlay_only", "execute_allowed", "auto_apply", "allowed_routes"],
            "properties": {
                "review_only": {"type": "boolean"},
                "draft_only": {"type": "boolean"},
                "overlay_only": {"type": "boolean"},
                "execute_allowed": {"type": "boolean"},
                "auto_apply": {"type": "boolean"},
                "allowed_routes": {"type": "array", "items": {"type": "string"}},
            },
        },
        "ReviewCopilotSummary": {
            "type": "object",
            "required": ["mode", "headline", "reasons", "priorities", "rule_opportunities", "batch_triage", "guardrails"],
            "properties": {
                "mode": {"type": "string"},
                "headline": {"type": "string"},
                "reasons": {"type": "array", "items": {"$ref": "#/components/schemas/ReviewCopilotReason"}},
                "priorities": {"type": "array", "items": {"$ref": "#/components/schemas/ReviewCopilotPriority"}},
                "rule_opportunities": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/ReviewCopilotRuleOpportunity"},
                },
                "batch_triage": {"type": "array", "items": {"$ref": "#/components/schemas/ReviewQueueBatchSuggestion"}},
                "guardrails": {"$ref": "#/components/schemas/ReviewCopilotGuardrails"},
            },
        },
        "ReviewBridge": {
            "type": "object",
            "required": [
                "mode",
                "next_step",
                "review_queue_path",
                "batch_triage_path",
                "rule_from_examples_path",
                "needs_review_count",
                "conflict_count",
                "blocked_count",
                "collection_focus_ids",
                "rule_opportunity_keys",
                "execute_allowed",
            ],
            "properties": {
                "mode": {"type": "string"},
                "next_step": {"type": "string"},
                "review_queue_path": {"type": "string"},
                "batch_triage_path": {"type": "string"},
                "rule_from_examples_path": {"type": "string"},
                "needs_review_count": {"type": "integer"},
                "conflict_count": {"type": "integer"},
                "blocked_count": {"type": "integer"},
                "collection_focus_ids": {"type": "array", "items": {"type": "string"}},
                "rule_opportunity_keys": {"type": "array", "items": {"type": "string"}},
                "execute_allowed": {"type": "boolean"},
            },
        },
        "LearnedSuggestion": {
            "type": "object",
            "required": [
                "signal_key",
                "signal_value",
                "suggestion_type",
                "suggestion_value",
                "confidence",
                "count",
                "confidence_label",
                "strength",
                "reuse_scope",
                "source",
                "reason",
                "explanation",
                "scope_reason",
            ],
            "properties": {
                "signal_key": {"type": "string"},
                "signal_value": {"type": "string"},
                "suggestion_type": {"type": "string"},
                "suggestion_value": {"type": "string"},
                "confidence": {"type": "number"},
                "count": {"type": "integer"},
                "confidence_label": {"type": "string"},
                "strength": {"type": "string"},
                "reuse_scope": {"type": "string", "enum": ["transient", "reusable"]},
                "source": {"type": "string"},
                "reason": {"type": "string"},
                "explanation": {"type": "string"},
                "scope_reason": {"type": "string"},
            },
        },
        "ManifestRow": {
            "type": "object",
            "required": [
                "row_id",
                "file_name",
                "media_type",
                "category",
                "title",
                "tags",
                "status",
                "error_code",
                "target_path",
                "target_suggestion",
                "confidence",
                "original_path",
                "notes",
                "ignore",
                "metadata",
            ],
            "properties": {
                "row_id": {"type": "string"},
                "id": {"type": "string"},
                "file_name": {"type": "string"},
                "media_type": {"type": "string"},
                "category": {"type": "string"},
                "title": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string"},
                "error_code": {"type": "string"},
                "target_path": {"type": "string"},
                "target_suggestion": {"type": "string"},
                "dedupe_of": {"type": "string"},
                "confidence": {"type": "number"},
                "original_path": {"type": "string"},
                "notes": {"type": "string"},
                "ignore": {"type": "boolean"},
                "review_bucket": {"type": "string", "enum": bucket_enum},
                "has_conflict": {"type": "boolean"},
                "edited": {"type": "boolean"},
                "collection_id": {"type": "string"},
                "collection_title": {"type": "string"},
                "collection_reason": {"type": "string"},
                "collection_confidence": {"type": "number"},
                "collection_capture_day": {"type": "string"},
                "collection_batch_hint": {"type": "string"},
                "collection_source_root": {"type": "string"},
                "collection_kind": {"type": "string"},
                "collection_next_step": {"type": "string"},
                "collection_explainability": {"type": "array", "items": {"type": "string"}},
                "learned_suggestions": {"type": "array", "items": {"$ref": "#/components/schemas/LearnedSuggestion"}},
                "review_explainability": {"$ref": "#/components/schemas/ReviewExplainability"},
                "metadata": {"type": "object", "additionalProperties": {"type": "string"}},
            },
        },
        "ReviewQueueSummary": {
            "type": "object",
            "required": ["total", "auto_safe", "needs_review", "conflict", "blocked"],
            "properties": {
                "total": {"type": "integer"},
                "auto_safe": {"type": "integer"},
                "needs_review": {"type": "integer"},
                "conflict": {"type": "integer"},
                "blocked": {"type": "integer"},
            },
        },
        "CollectionSummary": {
            "type": "object",
            "required": [
                "id",
                "title",
                "reason",
                "confidence",
                "row_ids",
                "kind",
                "next_step",
                "capture_day",
                "batch_hint",
                "source_root",
                "dominant_media_type",
                "media_types",
                "explainability",
            ],
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "reason": {"type": "string"},
                "confidence": {"type": "number"},
                "row_ids": {"type": "array", "items": {"type": "string"}},
                "kind": {"type": "string"},
                "next_step": {"type": "string"},
                "capture_day": {"type": "string"},
                "batch_hint": {"type": "string"},
                "source_root": {"type": "string"},
                "dominant_media_type": {"type": "string"},
                "media_types": {"type": "array", "items": {"type": "string"}},
                "explainability": {"type": "array", "items": {"type": "string"}},
            },
        },
        "ReviewQueueResponse": {
            "type": "object",
            "required": ["job_id", "manifest_path", "overlay_path", "summary", "collections", "rows", "returned"],
            "properties": {
                "job": {"type": "object"},
                "job_id": {"type": "string"},
                "manifest_path": {"type": "string"},
                "overlay_path": {"type": "string"},
                "overlay_updated_at": {"type": "string"},
                "summary": {"$ref": "#/components/schemas/ReviewQueueSummary"},
                "copilot_summary": {"$ref": "#/components/schemas/ReviewCopilotSummary"},
                "collections": {"type": "array", "items": {"$ref": "#/components/schemas/CollectionSummary"}},
                "rows": {"type": "array", "items": {"$ref": "#/components/schemas/ManifestRow"}},
                "returned": {"type": "integer"},
            },
        },
        "ReviewRuleAction": {
            "type": "object",
            "properties": {
                "set_category": {"type": "string"},
                "set_ignore": {"type": "boolean"},
                "target_pattern": {"type": "string"},
            },
        },
        "ReviewRuleCondition": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "statuses": {"type": "array", "items": {"type": "string"}},
                "media_types": {"type": "array", "items": {"type": "string"}},
                "categories": {"type": "array", "items": {"type": "string"}},
                "review_buckets": {"type": "array", "items": {"type": "string"}},
                "min_confidence": {"type": "number"},
                "max_confidence": {"type": "number"},
                "has_conflict": {"type": "boolean"},
                "ignore_state": {"type": "boolean"},
            },
        },
        "ReviewRuleApplyRequest": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "string"},
                "rule": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "ReviewRuleFromExamplesRequest": {
            "type": "object",
            "required": ["row_ids"],
            "properties": {
                "row_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5},
                "name": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "ReviewRuleDraftExplainability": {
            "type": "object",
            "required": [
                "selected_count",
                "selected_row_ids",
                "shared_media_types",
                "shared_review_buckets",
                "shared_query",
                "inferred_actions",
                "save_allowed",
                "apply_allowed",
            ],
            "properties": {
                "selected_count": {"type": "integer"},
                "selected_row_ids": {"type": "array", "items": {"type": "string"}},
                "shared_media_types": {"type": "array", "items": {"type": "string"}},
                "shared_review_buckets": {"type": "array", "items": {"type": "string"}},
                "shared_query": {"type": "string"},
                "inferred_actions": {"type": "array", "items": {"type": "string"}},
                "save_allowed": {"type": "boolean"},
                "apply_allowed": {"type": "boolean"},
            },
        },
        "ReviewRuleDraft": {
            "type": "object",
            "required": ["name", "scope", "description", "version", "mode", "draft_source", "conditions", "actions"],
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "scope": {"type": "string", "enum": ["manifest", "report", "jobs"]},
                "description": {"type": "string"},
                "version": {"type": "integer"},
                "mode": {"type": "string", "enum": ["draft_only"]},
                "draft_source": {"type": "string"},
                "conditions": {"$ref": "#/components/schemas/ReviewRuleCondition"},
                "actions": {"$ref": "#/components/schemas/ReviewRuleAction"},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "example_row_ids": {"type": "array", "items": {"type": "string"}},
                "explainability": {"$ref": "#/components/schemas/ReviewRuleDraftExplainability"},
            },
        },
        "ReviewRuleDraftResponse": {
            "type": "object",
            "required": [
                "job_id",
                "selected_count",
                "selected_row_ids",
                "mode",
                "save_allowed",
                "apply_allowed",
                "execute_allowed",
                "draft",
                "warnings",
            ],
            "properties": {
                "job_id": {"type": "string"},
                "selected_count": {"type": "integer"},
                "selected_row_ids": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string", "enum": ["draft_only"]},
                "save_allowed": {"type": "boolean"},
                "apply_allowed": {"type": "boolean"},
                "execute_allowed": {"type": "boolean"},
                "draft": {"$ref": "#/components/schemas/ReviewRuleDraft"},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        },
        "ReviewQueueBatchTriageRequest": {
            "type": "object",
            "required": ["row_ids"],
            "properties": {
                "row_ids": {"type": "array", "items": {"type": "string"}},
                "set_category": {"type": "string"},
                "set_ignore": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "ReviewQueueBatchTriageResponse": {
            "allOf": [
                {"$ref": "#/components/schemas/ReviewQueueResponse"},
                {
                    "type": "object",
                    "required": ["applied_count", "mode", "execute_allowed"],
                    "properties": {
                        "applied_count": {"type": "integer"},
                        "mode": {"type": "string", "enum": ["overlay_only"]},
                        "execute_allowed": {"type": "boolean"},
                    },
                },
            ]
        },
        "ReviewRuleApplyResponse": {
            "allOf": [
                {"$ref": "#/components/schemas/ReviewQueueResponse"},
                {
                    "type": "object",
                    "required": ["applied_rule_id", "matched_count", "mode", "execute_allowed"],
                    "properties": {
                        "applied_rule_id": {"type": "string"},
                        "matched_count": {"type": "integer"},
                        "mode": {"type": "string", "enum": ["overlay_only"]},
                        "execute_allowed": {"type": "boolean"},
                    },
                },
            ]
        },
        "JobReportPayload": {
            "type": "object",
            "properties": {
                "total": {"type": "integer"},
                "by_review_bucket": {"$ref": "#/components/schemas/ReviewQueueSummary"},
                "collection_count": {"type": "integer"},
                "collection_ids": {"type": "array", "items": {"type": "string"}},
                "collection_summaries": {"type": "array", "items": {"$ref": "#/components/schemas/CollectionSummary"}},
                "rows_with_learning_suggestions": {"type": "integer"},
                "learned_rule_count": {"type": "integer"},
                "reusable_learning_rule_count": {"type": "integer"},
                "review_copilot_summary": {"$ref": "#/components/schemas/ReviewCopilotSummary"},
                "review_bridge": {"$ref": "#/components/schemas/ReviewBridge"},
            },
            "additionalProperties": True,
        },
        "JobReportResponse": {
            "type": "object",
            "required": ["job_id", "report_path", "report"],
            "properties": {
                "job_id": {"type": "string"},
                "report_path": {"type": "string"},
                "report": {"$ref": "#/components/schemas/JobReportPayload"},
            },
        },
        "StrategyPack": {
            "type": "object",
            "required": [
                "id",
                "name",
                "description",
                "categories",
                "workers",
                "review_confidence_threshold",
                "default_rule_ids",
                "default_template_patterns",
                "defaults",
                "explainability",
            ],
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "categories": {"type": "array", "items": {"type": "string"}},
                "model": {"type": "string"},
                "workers": {"type": "integer"},
                "review_confidence_threshold": {"type": "number"},
                "default_rule_ids": {"type": "array", "items": {"type": "string"}},
                "default_template_patterns": {"type": "array", "items": {"type": "string"}},
                "defaults": {"type": "object", "additionalProperties": True},
                "explainability": {"type": "object", "additionalProperties": {"type": "string"}},
            },
        },
        "StrategyPackListResponse": {
            "type": "object",
            "required": ["items", "count", "active_strategy_pack_id"],
            "properties": {
                "items": {"type": "array", "items": {"$ref": "#/components/schemas/StrategyPack"}},
                "count": {"type": "integer"},
                "active_strategy_pack_id": {"type": "string"},
                "active_pack": {"$ref": "#/components/schemas/StrategyPack"},
            },
        },
        "WatchSource": {
            "type": "object",
            "required": ["id", "name", "input_root", "enabled", "strategy_pack_id", "created_at", "updated_at"],
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "input_root": {"type": "string"},
                "enabled": {"type": "boolean"},
                "strategy_pack_id": {"type": "string"},
                "created_at": {"type": "string"},
                "updated_at": {"type": "string"},
                "strategy_pack": {"$ref": "#/components/schemas/StrategyPack"},
            },
        },
        "WatchSourceListResponse": {
            "type": "object",
            "required": ["items", "count", "path"],
            "properties": {
                "items": {"type": "array", "items": {"$ref": "#/components/schemas/WatchSource"}},
                "count": {"type": "integer"},
                "path": {"type": "string"},
            },
        },
        "LearnedRuleListResponse": {
            "type": "object",
            "required": ["items", "count", "path"],
            "properties": {
                "items": {"type": "array", "items": {"$ref": "#/components/schemas/LearnedSuggestion"}},
                "count": {"type": "integer"},
                "path": {"type": "string"},
            },
        },
        "AnalyzeDefaults": {
            "type": "object",
            "required": ["model", "categories", "workers", "max_files", "max_total_mb", "max_file_mb", "offline"],
            "properties": {
                "model": {"type": "string"},
                "categories": {"type": "string"},
                "workers": {"type": "integer"},
                "max_files": {"type": "integer"},
                "max_total_mb": {"type": "number"},
                "max_file_mb": {"type": "number"},
                "offline": {"type": "boolean"},
            },
        },
        "InboxAction": {
            "type": "object",
            "required": ["method", "path", "payload"],
            "properties": {
                "method": {"type": "string"},
                "path": {"type": "string"},
                "payload": {"type": "object", "additionalProperties": True},
            },
        },
        "InboxBatch": {
            "type": "object",
            "required": [
                "id",
                "watch_source_id",
                "source_name",
                "input_root",
                "file_count",
                "file_paths",
                "strategy_pack_id",
                "analyze_job_id",
                "analyze_ready",
                "discovery_mode",
                "analyze_defaults",
                "analyze_action",
            ],
            "properties": {
                "id": {"type": "string"},
                "watch_source_id": {"type": "string"},
                "source_name": {"type": "string"},
                "input_root": {"type": "string"},
                "file_count": {"type": "integer"},
                "file_paths": {"type": "array", "items": {"type": "string"}},
                "strategy_pack_id": {"type": "string"},
                "analyze_job_id": {"type": "string"},
                "analyze_ready": {"type": "boolean"},
                "discovery_mode": {"type": "string"},
                "strategy_pack": {"$ref": "#/components/schemas/StrategyPack"},
                "analyze_defaults": {"$ref": "#/components/schemas/AnalyzeDefaults"},
                "analyze_action": {"$ref": "#/components/schemas/InboxAction"},
            },
        },
        "InboxAnalyzeRequest": {
            "type": "object",
            "required": ["watch_source_id"],
            "properties": {
                "watch_source_id": {"type": "string"},
                "batch_id": {"type": "string"},
                "strategy_pack_id": {"type": "string"},
                "model": {"type": "string"},
                "categories": {"type": "string"},
                "workers": {"type": "integer"},
                "max_files": {"type": "integer"},
                "max_total_mb": {"type": "number"},
                "max_file_mb": {"type": "number"},
                "offline": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "InboxAnalyzeResponse": {
            "type": "object",
            "required": ["job", "job_id", "mode", "batch", "review_next"],
            "properties": {
                "job": {"type": "object"},
                "job_id": {"type": "string"},
                "mode": {"type": "string"},
                "batch": {"$ref": "#/components/schemas/InboxBatch"},
                "strategy_pack": {"$ref": "#/components/schemas/StrategyPack"},
                "review_next": {"type": "object", "additionalProperties": True},
            },
        },
        "InboxScanResponse": {
            "type": "object",
            "required": ["items", "count", "mode", "analyze_route"],
            "properties": {
                "items": {"type": "array", "items": {"$ref": "#/components/schemas/InboxBatch"}},
                "count": {"type": "integer"},
                "mode": {"type": "string"},
                "analyze_route": {"type": "string"},
            },
        },
    }


def _yaml_dump(payload: dict[str, Any]) -> str:
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


def _generated_types() -> str:
    return """// AUTO-GENERATED from contracts/api/web_api.openapi.yaml. Do not edit manually.
export type JobKind = 'analyze' | 'apply' | 'rollback'
export type JobStatus = 'queued' | 'running' | 'cancelling' | 'succeeded' | 'failed' | 'cancelled'
export type InputMode = 'directory' | 'upload'

export interface JobSummary {
  total: number
  with_error: number
  by_media_type: Record<string, number>
  by_category: Record<string, number>
  by_status: Record<string, number>
  error_codes: Record<string, number>
  by_review_bucket?: Record<string, number>
  collection_count?: number
  collection_ids?: string[]
  manifest_path?: string
  report_path?: string
  rollback_manifest_path?: string
  input_mode?: InputMode
  input_root?: string
  output_root?: string
  dry_run?: boolean
  allowed_root?: string
}

export interface Job {
  id: string
  kind: JobKind
  status: JobStatus
  phase: string
  progress: number
  started_at?: string
  finished_at?: string
  retry_of?: string
  cancel_requested_at?: string
  summary?: JobSummary
  latest_error?: string
  manifest_path?: string
  report_path?: string
  rollback_manifest_path?: string
  dry_run_verified?: boolean
  strict_integrity_ready?: boolean
}

export interface JobEvent {
  id?: string
  timestamp: string
  level: string
  message: string
  fields?: Record<string, unknown>
}

export interface ReviewExplainability {
  bucket: 'auto_safe' | 'needs_review' | 'conflict' | 'blocked'
  reason_codes: string[]
  reasons: string[]
  collection_confidence: number
  learned_suggestion_count: number
  edited: boolean
  has_conflict: boolean
}

export interface ManifestRow {
  row_id: string
  id: string
  file_name: string
  media_type: string
  category: string
  title: string
  tags: string[]
  status: string
  error_code: string
  target_path: string
  target_suggestion: string
  dedupe_of?: string
  confidence: number
  original_path: string
  notes: string
  ignore: boolean
  review_bucket?: 'auto_safe' | 'needs_review' | 'conflict' | 'blocked'
  has_conflict?: boolean
  edited?: boolean
  collection_id?: string
  collection_title?: string
  collection_reason?: string
  collection_confidence?: number
  collection_capture_day?: string
  collection_batch_hint?: string
  collection_source_root?: string
  collection_kind?: string
  collection_next_step?: string
  collection_explainability?: string[]
  learned_suggestions?: LearnedSuggestion[]
  review_explainability?: ReviewExplainability
  metadata: Record<string, string>
}

export interface ManifestRowPatch {
  row_id: string
  category?: string
  title?: string
  tags?: string[]
  notes?: string
  target_suggestion?: string
  ignore?: boolean
}

export interface ManifestConflict {
  id: string
  row_id: string
  type: string
  severity: 'warning' | 'error'
  source_path: string
  target_path: string
  reason: string
  suggested_target?: string
  status: 'open' | 'resolved' | 'ignored'
}

export interface PreviewPayload {
  row_id: string
  media_type: string
  thumbnail_url?: string
  summary?: string
  duration_s?: number
  pages?: number
  mime?: string
  extra?: Record<string, string>
}

export interface SavedView {
  id: string
  name: string
  scope: 'manifest' | 'report' | 'jobs'
  query: Record<string, string>
  created_at: string
}

export interface NamingTemplate {
  id: string
  name: string
  pattern: string
  description?: string
  created_at: string
}

export interface ReviewQueueSummary {
  total: number
  auto_safe: number
  needs_review: number
  conflict: number
  blocked: number
}

export interface CollectionSummary {
  id: string
  title: string
  reason: string
  confidence: number
  row_ids: string[]
  kind: string
  next_step: string
  capture_day: string
  batch_hint: string
  source_root: string
  dominant_media_type: string
  media_types: string[]
  explainability: string[]
}

export interface ReviewRuleCondition {
  query?: string
  statuses?: string[]
  media_types?: string[]
  categories?: string[]
  review_buckets?: string[]
  min_confidence?: number
  max_confidence?: number
  has_conflict?: boolean
  ignore_state?: boolean
}

export interface ReviewRuleAction {
  set_category?: string
  set_ignore?: boolean
  target_pattern?: string
}

export interface ReviewRule {
  id: string
  name: string
  scope: 'manifest' | 'report' | 'jobs'
  description?: string
  version: number
  conditions: ReviewRuleCondition
  actions: ReviewRuleAction
  created_at?: string
  updated_at?: string
}

export interface RulePreview {
  matched_row_ids: string[]
  matched_count: number
  patch_preview: Record<string, Record<string, unknown>>
}

export interface LearnedSuggestion {
  signal_key: string
  signal_value: string
  suggestion_type: string
  suggestion_value: string
  confidence: number
  count: number
  confidence_label: string
  strength: string
  reuse_scope: 'transient' | 'reusable'
  source: string
  reason: string
  explanation: string
  scope_reason: string
}

export interface LearnedRule extends LearnedSuggestion {
  id: string
  updated_at: string
}

export interface ReviewQueueBatchSuggestion {
  id: string
  kind: 'bucket' | 'collection'
  label: string
  review_bucket: 'auto_safe' | 'needs_review' | 'conflict' | 'blocked'
  collection_id?: string
  count: number
  row_ids: string[]
  reason: string
  next_step: string
}

export interface ReviewCopilotReason {
  key: string
  title: string
  count: number
  detail: string
}

export interface ReviewCopilotPriority {
  row_id: string
  file_name: string
  bucket: 'auto_safe' | 'needs_review' | 'conflict' | 'blocked'
  reason: string
  suggested_action: string
  confidence: number
}

export interface ReviewCopilotRuleOpportunity {
  key: string
  title: string
  reason: string
  row_ids: string[]
  suggested_action: string
}

export interface ReviewCopilotGuardrails {
  review_only: boolean
  draft_only: boolean
  overlay_only: boolean
  execute_allowed: boolean
  auto_apply: boolean
  allowed_routes: string[]
}

export interface ReviewCopilotSummary {
  mode: string
  headline: string
  reasons: ReviewCopilotReason[]
  priorities: ReviewCopilotPriority[]
  rule_opportunities: ReviewCopilotRuleOpportunity[]
  batch_triage: ReviewQueueBatchSuggestion[]
  guardrails: ReviewCopilotGuardrails
}

export interface ReviewBridge {
  mode: string
  next_step: string
  review_queue_path: string
  batch_triage_path: string
  rule_from_examples_path: string
  needs_review_count: number
  conflict_count: number
  blocked_count: number
  collection_focus_ids: string[]
  rule_opportunity_keys: string[]
  execute_allowed: boolean
}

export interface ReviewQueueResponse {
  job: Job | null
  job_id: string
  manifest_path: string
  overlay_path: string
  overlay_updated_at?: string
  summary: ReviewQueueSummary
  copilot_summary?: ReviewCopilotSummary
  collections: CollectionSummary[]
  rows: ManifestRow[]
  returned: number
}

export interface ReviewRuleDraftExplainability {
  selected_count: number
  selected_row_ids: string[]
  shared_media_types: string[]
  shared_review_buckets: string[]
  shared_query: string
  inferred_actions: string[]
  save_allowed: boolean
  apply_allowed: boolean
}

export interface ReviewRuleDraft extends Omit<ReviewRule, 'id'> {
  id?: string
  mode: 'draft_only'
  draft_source: string
  warnings: string[]
  example_row_ids: string[]
  explainability: ReviewRuleDraftExplainability
}

export interface ReviewRuleDraftResponse {
  job_id: string
  selected_count: number
  selected_row_ids: string[]
  mode: 'draft_only'
  save_allowed: false
  apply_allowed: false
  execute_allowed: false
  draft: ReviewRuleDraft
  warnings: string[]
}

export interface ReviewRuleApplyResponse extends ReviewQueueResponse {
  applied_rule_id: string
  matched_count: number
  mode: 'overlay_only'
  execute_allowed: false
}

export interface ReviewQueueBatchTriageResponse extends ReviewQueueResponse {
  applied_count: number
  mode: 'overlay_only'
  execute_allowed: false
}

export interface JobReportPayload extends Record<string, unknown> {
  total?: number
  by_review_bucket?: ReviewQueueSummary
  collection_count?: number
  collection_ids?: string[]
  collection_summaries?: CollectionSummary[]
  rows_with_learning_suggestions?: number
  learned_rule_count?: number
  reusable_learning_rule_count?: number
  review_copilot_summary?: ReviewCopilotSummary
  review_bridge?: ReviewBridge
}

export interface JobReportResponse {
  job_id: string
  report_path: string
  report: JobReportPayload
}

export interface StrategyPack {
  id: string
  name: string
  description: string
  categories: string[]
  model?: string
  workers: number
  review_confidence_threshold: number
  default_rule_ids: string[]
  default_template_patterns: string[]
  defaults: Record<string, unknown>
  explainability: Record<string, string>
}

export interface WatchSource {
  id: string
  name: string
  input_root: string
  enabled: boolean
  strategy_pack_id: string
  created_at: string
  updated_at: string
  strategy_pack?: StrategyPack
}

export interface InboxBatch {
  id: string
  watch_source_id: string
  source_name: string
  input_root: string
  file_count: number
  file_paths: string[]
  strategy_pack_id: string
  analyze_job_id: string
  analyze_ready: boolean
  discovery_mode: string
  strategy_pack?: StrategyPack
  analyze_defaults: {
    model: string
    categories: string
    workers: number
    max_files: number
    max_total_mb: number
    max_file_mb: number
    offline: boolean
  }
  analyze_action: {
    method: string
    path: string
    payload: Record<string, unknown>
  }
}

export interface InboxScanResponse {
  items: InboxBatch[]
  count: number
  mode: string
  analyze_route: string
}

export interface InboxAnalyzeRequest {
  watch_source_id: string
  batch_id?: string
  strategy_pack_id?: string
  model?: string
  categories?: string
  workers?: number
  max_files?: number
  max_total_mb?: number
  max_file_mb?: number
  offline?: boolean
}

export interface InboxAnalyzeResponse {
  job: Job
  job_id: string
  mode: string
  batch: InboxBatch
  strategy_pack?: StrategyPack
  review_next: Record<string, unknown>
}

export interface RuntimeSettings {
  workspace_root: string
  runtime_env_path: string
  input_root: string
  output_root: string
  allowed_root: string
  manifest_root: string
  artifact_root: string
  has_api_key: boolean
  api_key_masked: string
  api_key_source: 'env' | 'runtime_env' | 'missing' // pragma: allowlist secret
  api_key_status: 'configured' | 'missing' | 'placeholder' // pragma: allowlist secret
  model: string
  model_source: 'env' | 'runtime_env' | 'default'
  active_strategy_pack_id: string
  input_root_exists: boolean
  output_root_exists: boolean
  ready: boolean
  analyze_defaults: {
    workers: number
    categories: string[]
    max_files: number
    max_total_mb: number
    max_file_mb: number
  }
  missing: string[]
  warnings: string[]
  checked_at: string
}

export interface JobsQuery {
  q?: string
  kind?: string
  status?: string
  from?: string
  to?: string
}
"""


def _generated_client() -> str:
    return """// AUTO-GENERATED from contracts/api/web_api.openapi.yaml. Do not edit manually.
export const API_ROOT = '/api'

export const apiContract = {
  healthz: '/healthz',
  listJobs: '/api/jobs',
  listJobsHistory: '/api/jobs/history',
  streamJobs: '/api/jobs/stream',
  getJob: (jobId: string) => `/api/jobs/${jobId}`,
  getJobEvents: (jobId: string) => `/api/jobs/${jobId}/events`,
  streamJobEvents: (jobId: string) => `/api/jobs/${jobId}/events/stream`,
  streamJob: (jobId: string) => `/api/jobs/${jobId}/stream`,
  cancelJob: (jobId: string) => `/api/jobs/${jobId}/cancel`,
  retryJob: (jobId: string) => `/api/jobs/${jobId}/retry`,
  getManifest: (jobId: string) => `/api/jobs/${jobId}/manifest`,
  getManifestView: (jobId: string) => `/api/jobs/${jobId}/manifest/view`,
  getManifestPreview: (jobId: string, rowId: string) => `/api/jobs/${jobId}/manifest/${rowId}/preview`,
  patchManifestRow: (jobId: string, rowId: string) => `/api/jobs/${jobId}/manifest/rows/${rowId}`,
  patchManifestBatch: (jobId: string) => `/api/jobs/${jobId}/manifest/batch`,
  getManifestConflicts: (jobId: string) => `/api/jobs/${jobId}/manifest/conflicts`,
  resolveManifestConflicts: (jobId: string) => `/api/jobs/${jobId}/manifest/conflicts/resolve`,
  getReviewQueue: (jobId: string) => `/api/jobs/${jobId}/review-queue`,
  getReport: (jobId: string) => `/api/jobs/${jobId}/report`,
  getAudit: (jobId: string) => `/api/jobs/${jobId}/audit`,
  createAnalyzeJob: '/api/jobs/analyze',
  createApplyJob: '/api/jobs/apply',
  createRollbackJob: '/api/jobs/rollback',
  getRuntimeSettings: '/api/preferences/runtime',
  upsertRuntimeSettings: '/api/preferences/runtime',
  validateRuntimeSettings: '/api/preferences/runtime/validate',
  listSavedViews: '/api/preferences/views',
  upsertSavedView: '/api/preferences/views',
  deleteSavedView: '/api/preferences/views',
  listNamingTemplates: '/api/preferences/naming-templates',
  upsertNamingTemplate: '/api/preferences/naming-templates',
  deleteNamingTemplate: '/api/preferences/naming-templates',
  listReviewRules: '/api/preferences/review-rules',
  upsertReviewRule: '/api/preferences/review-rules',
  deleteReviewRule: '/api/preferences/review-rules',
  previewReviewRule: (jobId: string) => `/api/jobs/${jobId}/review-rules/preview`,
  applyReviewRule: (jobId: string) => `/api/jobs/${jobId}/review-rules/apply`,
  draftReviewRuleFromExamples: (jobId: string) => `/api/jobs/${jobId}/review-rules/from-examples`,
  batchTriageReviewQueue: (jobId: string) => `/api/jobs/${jobId}/review-queue/batch-triage`,
  listStrategyPacks: '/api/preferences/strategy-packs',
  listLearnedRules: '/api/preferences/learned-rules',
  resetLearnedRules: '/api/preferences/learned-rules',
  listWatchSources: '/api/preferences/watch-sources',
  upsertWatchSource: '/api/preferences/watch-sources',
  deleteWatchSource: '/api/preferences/watch-sources',
  scanInbox: '/api/inbox/scan',
  startInboxAnalyze: '/api/inbox/analyze',
} as const
"""


def _generated_index() -> str:
    return """// AUTO-GENERATED from contracts/api/web_api.openapi.yaml. Do not edit manually.
export * from './types'
export * from './client'
"""


def _outputs() -> dict[Path, str]:
    openapi = _load_openapi()
    return {
        OPENAPI_OUTPUT: _yaml_dump(openapi),
        GENERATED_WEBUI_DIR / "types.ts": _generated_types(),
        GENERATED_WEBUI_DIR / "client.ts": _generated_client(),
        GENERATED_WEBUI_DIR / "index.ts": _generated_index(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate API contract and WebUI client/types from the Fileorganize Web API")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo_root = Path(args.root).resolve()
    if repo_root != REPO_ROOT:
        raise SystemExit("generate_api_contract.py must run from repository root")

    outputs = _outputs()
    stale: list[str] = []
    for path, rendered in outputs.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != rendered:
            stale.append(str(path.relative_to(REPO_ROOT)))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(rendered, encoding="utf-8")
    if stale and args.check:
        print("❌ generate_api_contract: stale outputs detected")
        for item in stale:
            print(f"- {item}")
        print("fix: python3 tooling/scripts/generate_api_contract.py")
        return 1
    print(f"✅ generate_api_contract: {'checked' if args.check else 'rendered'}")
    print(f"outputs={len(outputs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
