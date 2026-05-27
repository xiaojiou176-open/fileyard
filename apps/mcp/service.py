from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from apps.api.web_api import create_app


class FilemanMcpError(RuntimeError):
    """Raised when the MCP thin facade receives a non-2xx Web API response."""


def _extract_detail(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return ""


@dataclass
class FilemanMcpApiFacade:
    """Thin in-process facade that reuses the current Web API contract."""

    _client: TestClient | None = None

    def start(self) -> "FilemanMcpApiFacade":
        if self._client is None:
            self._client = TestClient(create_app())
            self._client.__enter__()
        return self

    def close(self) -> None:
        if self._client is not None:
            self._client.__exit__(None, None, None)
            self._client = None

    @property
    def client(self) -> TestClient:
        if self._client is None:
            self.start()
        assert self._client is not None
        return self._client

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self.client.request(method.upper(), path, params=params, json=json_payload)
        if response.is_success:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return {"items": payload}

        detail = ""
        try:
            detail = _extract_detail(response.json())
        except Exception:
            detail = ""
        message = detail or f"{response.status_code} {response.reason_phrase}".strip()
        raise FilemanMcpError(message)

    def list_jobs(self, *, kind: str | None = None, status: str | None = None) -> dict[str, Any]:
        items = self.request_json("GET", "/api/jobs").get("items")
        if items is None:
            raw_items = self.client.get("/api/jobs").json()
            if isinstance(raw_items, list):
                items = raw_items
            else:
                items = []
        filtered = list(items) if isinstance(items, list) else []
        if kind:
            filtered = [item for item in filtered if str(item.get("kind", "") or "") == kind]
        if status:
            filtered = [item for item in filtered if str(item.get("status", "") or "") == status]
        return {"count": len(filtered), "items": filtered}

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.request_json("GET", f"/api/jobs/{job_id}")

    def get_runtime_settings(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/preferences/runtime")

    def create_analyze_job(
        self,
        *,
        input_directory: str,
        strategy_pack_id: str | None = None,
        watch_source_id: str | None = None,
        trigger_source: str = "manual",
        model: str | None = None,
        categories: str | None = None,
        workers: int | None = None,
        max_files: int | None = None,
        max_total_mb: float | None = None,
        max_file_mb: float | None = None,
        offline: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "input_mode": "directory",
            "input_directory": input_directory,
            "trigger_source": trigger_source,
            "offline": offline,
        }
        if strategy_pack_id:
            payload["strategy_pack_id"] = strategy_pack_id
        if watch_source_id:
            payload["watch_source_id"] = watch_source_id
        if model:
            payload["model"] = model
        if categories:
            payload["categories"] = categories
        if workers is not None:
            payload["workers"] = workers
        if max_files is not None:
            payload["max_files"] = max_files
        if max_total_mb is not None:
            payload["max_total_mb"] = max_total_mb
        if max_file_mb is not None:
            payload["max_file_mb"] = max_file_mb
        return self.request_json("POST", "/api/jobs/analyze", json_payload=payload)

    def get_review_queue(self, job_id: str, *, limit: int = 500) -> dict[str, Any]:
        return self.request_json("GET", f"/api/jobs/{job_id}/review-queue", params={"limit": limit})

    def get_manifest(self, job_id: str, *, limit: int = 500, view: bool = False) -> dict[str, Any]:
        suffix = "view" if view else ""
        path = f"/api/jobs/{job_id}/manifest/{suffix}".rstrip("/")
        return self.request_json("GET", path, params={"limit": limit})

    def patch_manifest_row(self, job_id: str, row_id: str, *, patch: dict[str, Any]) -> dict[str, Any]:
        return self.request_json(
            "PATCH",
            f"/api/jobs/{job_id}/manifest/rows/{row_id}",
            json_payload={"patch": patch},
        )

    def patch_manifest_batch(self, job_id: str, *, operations: list[dict[str, Any]]) -> dict[str, Any]:
        return self.request_json(
            "POST",
            f"/api/jobs/{job_id}/manifest/batch",
            json_payload={"operations": operations},
        )

    def preview_review_rule(
        self,
        job_id: str,
        *,
        rule_id: str | None = None,
        rule: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if rule_id:
            payload["rule_id"] = rule_id
        if rule is not None:
            payload["rule"] = rule
        return self.request_json("POST", f"/api/jobs/{job_id}/review-rules/preview", json_payload=payload)

    def apply_review_rule(
        self,
        job_id: str,
        *,
        rule_id: str | None = None,
        rule: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if rule_id:
            payload["rule_id"] = rule_id
        if rule is not None:
            payload["rule"] = rule
        return self.request_json("POST", f"/api/jobs/{job_id}/review-rules/apply", json_payload=payload)

    def create_apply_preview(
        self,
        *,
        analyze_job_id: str | None = None,
        manifest_path: str | None = None,
        output_root: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"execute": False}
        if analyze_job_id:
            payload["analyze_job_id"] = analyze_job_id
        if manifest_path:
            payload["manifest_path"] = manifest_path
        if output_root:
            payload["output_root"] = output_root
        return self.request_json("POST", "/api/jobs/apply", json_payload=payload)

    def get_report(self, job_id: str) -> dict[str, Any]:
        return self.request_json("GET", f"/api/jobs/{job_id}/report")

    def list_strategy_packs(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/preferences/strategy-packs")

    def list_watch_sources(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/preferences/watch-sources")

    def scan_inbox(self) -> dict[str, Any]:
        return self.request_json("POST", "/api/inbox/scan")

    def start_inbox_analyze(
        self,
        *,
        watch_source_id: str,
        batch_id: str | None = None,
        strategy_pack_id: str | None = None,
        model: str | None = None,
        categories: str | None = None,
        workers: int | None = None,
        max_files: int | None = None,
        max_total_mb: float | None = None,
        max_file_mb: float | None = None,
        offline: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"watch_source_id": watch_source_id, "offline": offline}
        if batch_id:
            payload["batch_id"] = batch_id
        if strategy_pack_id:
            payload["strategy_pack_id"] = strategy_pack_id
        if model:
            payload["model"] = model
        if categories:
            payload["categories"] = categories
        if workers is not None:
            payload["workers"] = workers
        if max_files is not None:
            payload["max_files"] = max_files
        if max_total_mb is not None:
            payload["max_total_mb"] = max_total_mb
        if max_file_mb is not None:
            payload["max_file_mb"] = max_file_mb
        return self.request_json("POST", "/api/inbox/analyze", json_payload=payload)

    def get_safety_boundary_text(self) -> str:
        return (
            "# Fileman MCP safety boundary\n\n"
            "- Fileman MCP is local-first and review-first.\n"
            "- Tools may inspect jobs, review queues, manifests, reports, strategy packs, and watch sources.\n"
            "- Safe write tools only patch the overlay or create draft/dry-run jobs.\n"
            "- MCP v1 does not expose `apply.execute`, direct file mutation shortcuts, or rollback creation.\n"
            "- Agents must keep `manifest -> overlay -> resolved snapshot -> dry-run -> execute` intact.\n"
        )

    def get_tool_matrix(self) -> dict[str, Any]:
        return {
            "server": "Fileman MCP",
            "mode": "local-first stdio",
            "v1_scope": "safe thin facade",
            "tools": [
                {"name": "jobs.list", "route": "/api/jobs", "safety": "read-only"},
                {"name": "jobs.get", "route": "/api/jobs/{job_id}", "safety": "read-only"},
                {"name": "runtime.settings.get", "route": "/api/preferences/runtime", "safety": "read-only"},
                {"name": "analyze.create", "route": "/api/jobs/analyze", "safety": "creates analyze job only"},
                {"name": "review_queue.get", "route": "/api/jobs/{job_id}/review-queue", "safety": "read-only"},
                {"name": "manifest.get", "route": "/api/jobs/{job_id}/manifest/view", "safety": "read-only"},
                {"name": "manifest.patch_row", "route": "/api/jobs/{job_id}/manifest/rows/{row_id}", "safety": "overlay-only"},
                {"name": "manifest.batch_patch", "route": "/api/jobs/{job_id}/manifest/batch", "safety": "overlay-only"},
                {"name": "review_rule.preview", "route": "/api/jobs/{job_id}/review-rules/preview", "safety": "read-only preview"},
                {"name": "review_rule.apply", "route": "/api/jobs/{job_id}/review-rules/apply", "safety": "overlay-only"},
                {"name": "apply.preview", "route": "/api/jobs/apply", "safety": "dry-run job only"},
                {"name": "report.get", "route": "/api/jobs/{job_id}/report", "safety": "read-only"},
                {"name": "strategy_packs.list", "route": "/api/preferences/strategy-packs", "safety": "read-only"},
                {"name": "watch_sources.list", "route": "/api/preferences/watch-sources", "safety": "read-only"},
                {"name": "inbox.scan", "route": "/api/inbox/scan", "safety": "discovery-only"},
                {"name": "inbox.analyze", "route": "/api/inbox/analyze", "safety": "creates analyze job only"},
            ],
            "deferred": ["apply.execute", "rollback.create", "auto-resolve-and-execute"],
        }

    def get_review_queue_resource(self, job_id: str) -> str:
        return _to_json_text(self.get_review_queue(job_id))

    def get_manifest_resource(self, job_id: str) -> str:
        return _to_json_text(self.get_manifest(job_id, view=True))

    def get_report_resource(self, job_id: str) -> str:
        return _to_json_text(self.get_report(job_id))


def _to_json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
