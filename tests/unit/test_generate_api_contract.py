from __future__ import annotations

from pathlib import Path

from tooling.scripts.generate_api_contract import _outputs


def test_generate_api_contract_includes_wave2_and_wave3_routes_and_safety_shapes() -> None:
    outputs = {str(path.relative_to(Path.cwd())): rendered for path, rendered in _outputs().items()}
    openapi = outputs["contracts/api/web_api.openapi.yaml"]
    types_ts = outputs["contracts/api/generated/webui/types.ts"]
    client_ts = outputs["contracts/api/generated/webui/client.ts"]

    assert "/api/jobs/{job_id}/review-rules/from-examples:" in openapi
    assert "/api/jobs/{job_id}/review-queue/batch-triage:" in openapi
    assert "/api/inbox/analyze:" in openapi
    assert "ReviewRuleDraftResponse" in openapi
    assert "Overlay-only batch triage response" in openapi
    assert "InboxScanResponse" in openapi

    assert "export interface ReviewCopilotSummary" in types_ts
    assert "export interface ReviewQueueResponse" in types_ts
    assert "execute_allowed: false" in types_ts
    assert "review_explainability?: ReviewExplainability" in types_ts
    assert "export interface InboxAnalyzeResponse" in types_ts
    assert "collection_summaries?: CollectionSummary[]" in types_ts
    assert "reuse_scope: 'transient' | 'reusable'" in types_ts
    assert "scope_reason: string" in types_ts

    assert "draftReviewRuleFromExamples" in client_ts
    assert "batchTriageReviewQueue" in client_ts
    assert "startInboxAnalyze" in client_ts
