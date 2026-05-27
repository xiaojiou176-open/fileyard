#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.mcp.service import FilemanMcpApiFacade  # noqa: E402

MCP_NAME = "Fileman MCP"
MCP_VERSION = "1.0.0"
MCP_INSTRUCTIONS = (
    "Fileman MCP is a local-first, review-first facade over the Fileman workbench. "
    "Use it to inspect jobs, review queues, manifests, reports, strategy packs, "
    "watch sources, and to apply safe overlay-only edits or dry-run apply previews. "
    "Do not expect direct file-mutation shortcuts or bypasses around review."
)


def _read_only_annotations(title: str) -> ToolAnnotations:
    return ToolAnnotations(title=title, readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _safe_write_annotations(title: str) -> ToolAnnotations:
    return ToolAnnotations(title=title, readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


def create_mcp_server(api: FilemanMcpApiFacade | None = None) -> FastMCP:
    facade = api or FilemanMcpApiFacade()
    mcp = FastMCP(
        MCP_NAME,
        instructions=MCP_INSTRUCTIONS,
        json_response=True,
        log_level=os.environ.get("FILEMAN_MCP_LOG_LEVEL", "INFO"),
    )

    @mcp.tool(
        name="jobs.list",
        description="List current Fileman jobs from the local workspace job store.",
        annotations=_read_only_annotations("List jobs"),
    )
    def list_jobs() -> dict[str, Any]:
        """Read-only job inventory for agents that need to pick a job before review."""

        return facade.list_jobs()

    @mcp.tool(
        name="jobs.get",
        description="Get one Fileman job by id.",
        annotations=_read_only_annotations("Get job"),
    )
    def get_job(job_id: str) -> dict[str, Any]:
        """Read one job record, including summary and status."""

        return facade.get_job(job_id)

    @mcp.tool(
        name="runtime.settings.get",
        description="Read the current local runtime settings.",
        annotations=_read_only_annotations("Get runtime settings"),
    )
    def get_runtime_settings() -> dict[str, Any]:
        """Read workspace-local runtime defaults and active pack selection."""

        return facade.get_runtime_settings()

    @mcp.tool(
        name="analyze.create",
        description="Create an analyze job without mutating files. Review still happens later.",
        annotations=_safe_write_annotations("Create analyze job"),
    )
    def create_analyze(
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
        """Create an analyze job that drafts a manifest. It does not apply file changes."""

        return facade.create_analyze_job(
            input_mode="directory",
            input_directory=input_directory,
            strategy_pack_id=strategy_pack_id,
            watch_source_id=watch_source_id,
            trigger_source=trigger_source,
            model=model,
            categories=categories,
            workers=workers,
            max_files=max_files,
            max_total_mb=max_total_mb,
            max_file_mb=max_file_mb,
            offline=offline,
        )

    @mcp.tool(
        name="review_queue.get",
        description="Get the review queue with deterministic copilot hints and collection slices.",
        annotations=_read_only_annotations("Get review queue"),
    )
    def get_review_queue(job_id: str, limit: int = 200) -> dict[str, Any]:
        """Read the review queue for one analyze job."""

        return facade.get_review_queue(job_id, limit=limit)

    @mcp.tool(
        name="manifest.get",
        description="Get the manifest view for one job. Defaults to the resolved review view.",
        annotations=_read_only_annotations("Get manifest view"),
    )
    def get_manifest(job_id: str, resolved: bool = True, limit: int = 200) -> dict[str, Any]:
        """Read the manifest or manifest view without executing any file operations."""

        return facade.get_manifest(job_id, view=resolved, limit=limit)

    @mcp.tool(
        name="manifest.patch_row",
        description="Patch one manifest row through the overlay only.",
        annotations=_safe_write_annotations("Patch manifest row"),
    )
    def patch_manifest_row(job_id: str, row_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Apply one overlay-only row patch."""

        return facade.patch_manifest_row(job_id, row_id, patch=patch)

    @mcp.tool(
        name="manifest.batch_patch",
        description="Patch multiple manifest rows through the overlay only.",
        annotations=_safe_write_annotations("Batch patch manifest"),
    )
    def patch_manifest_batch(job_id: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply multiple overlay-only row patches."""

        return facade.patch_manifest_batch(job_id, operations=operations)

    @mcp.tool(
        name="review_rule.preview",
        description="Preview a review rule against the current review queue without changing anything.",
        annotations=_read_only_annotations("Preview review rule"),
    )
    def preview_review_rule(job_id: str, rule_id: str | None = None, rule: dict[str, Any] | None = None) -> dict[str, Any]:
        """Preview a saved or inline review rule."""

        return facade.preview_review_rule(job_id, rule_id=rule_id, rule=rule)

    @mcp.tool(
        name="review_rule.apply",
        description="Apply a review rule to the overlay only. This does not execute file changes.",
        annotations=_safe_write_annotations("Apply review rule"),
    )
    def apply_review_rule(job_id: str, rule_id: str | None = None, rule: dict[str, Any] | None = None) -> dict[str, Any]:
        """Apply a review rule to the overlay-only review state."""

        return facade.apply_review_rule(job_id, rule_id=rule_id, rule=rule)

    @mcp.tool(
        name="apply.preview",
        description="Create an apply job in dry-run mode only.",
        annotations=_safe_write_annotations("Create apply preview"),
    )
    def create_apply_preview(
        analyze_job_id: str | None = None,
        manifest_path: str | None = None,
        output_root: str | None = None,
    ) -> dict[str, Any]:
        """Create a dry-run apply job. Execute mode is intentionally unavailable in MCP v1."""

        return facade.create_apply_preview(
            analyze_job_id=analyze_job_id,
            manifest_path=manifest_path,
            output_root=output_root,
        )

    @mcp.tool(
        name="report.get",
        description="Get one persisted report plus the review bridge metadata.",
        annotations=_read_only_annotations("Get report"),
    )
    def get_report(job_id: str) -> dict[str, Any]:
        """Read one report payload and the follow-up review routing metadata."""

        return facade.get_report(job_id)

    @mcp.tool(
        name="strategy_packs.list",
        description="List repo-shipped strategy packs and the active local default.",
        annotations=_read_only_annotations("List strategy packs"),
    )
    def list_strategy_packs() -> dict[str, Any]:
        """Read strategy packs without changing runtime settings."""

        return facade.list_strategy_packs()

    @mcp.tool(
        name="watch_sources.list",
        description="List local-first watch sources and their linked strategy packs.",
        annotations=_read_only_annotations("List watch sources"),
    )
    def list_watch_sources() -> dict[str, Any]:
        """Read watch source metadata from workspace-local preferences."""

        return facade.list_watch_sources()

    @mcp.tool(
        name="inbox.scan",
        description="Run inbox discovery only. This does not auto-start analyze or apply.",
        annotations=_read_only_annotations("Scan inbox"),
    )
    def scan_inbox() -> dict[str, Any]:
        """Discover inbox batches without triggering autonomous follow-up actions."""

        return facade.scan_inbox()

    @mcp.tool(
        name="inbox.analyze",
        description="Create an analyze job from one watch source and optional discovered batch id.",
        annotations=_safe_write_annotations("Analyze inbox batch"),
    )
    def analyze_inbox(
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
        """Launch analyze from the inbox surface without turning discovery into autonomy."""

        return facade.start_inbox_analyze(
            watch_source_id=watch_source_id,
            batch_id=batch_id,
            strategy_pack_id=strategy_pack_id,
            model=model,
            categories=categories,
            workers=workers,
            max_files=max_files,
            max_total_mb=max_total_mb,
            max_file_mb=max_file_mb,
            offline=offline,
        )

    @mcp.resource(
        "fileman://workflow/safety-boundary",
        name="workflow-safety-boundary",
        title="Fileman safety boundary",
        description="Human-readable summary of the review-first and dry-run guardrails.",
        mime_type="text/markdown",
    )
    def safety_boundary() -> str:
        return facade.get_safety_boundary_text()

    @mcp.resource(
        "fileman://workflow/tool-matrix",
        name="workflow-tool-matrix",
        title="Fileman MCP tool matrix",
        description="Machine-readable list of MCP v1 tools and their underlying safety class.",
        mime_type="application/json",
    )
    def tool_matrix() -> str:
        return json.dumps(facade.get_tool_matrix(), ensure_ascii=False, indent=2)

    @mcp.resource(
        "fileman://jobs/{job_id}/review-queue",
        name="job-review-queue",
        title="Review queue resource",
        description="Read-only review queue snapshot for one job.",
        mime_type="application/json",
    )
    def review_queue_resource(job_id: str) -> str:
        return facade.get_review_queue_resource(job_id)

    @mcp.resource(
        "fileman://jobs/{job_id}/manifest-view",
        name="job-manifest-view",
        title="Manifest view resource",
        description="Read-only manifest view snapshot for one job.",
        mime_type="application/json",
    )
    def manifest_resource(job_id: str) -> str:
        return facade.get_manifest_resource(job_id)

    @mcp.resource(
        "fileman://jobs/{job_id}/report",
        name="job-report",
        title="Report resource",
        description="Read-only report snapshot for one job.",
        mime_type="application/json",
    )
    def report_resource(job_id: str) -> str:
        return facade.get_report_resource(job_id)

    @mcp.resource(
        "fileman://docs/{doc_id}",
        name="fileman-docs",
        title="Fileman docs resource",
        description="Read an allowlisted public Fileman document for agent/developer context.",
        mime_type="text/markdown",
    )
    def docs_resource(doc_id: str) -> str:
        doc_map = {
            "overview": REPO_ROOT / "README.md",
            "usage": REPO_ROOT / "docs" / "usage.md",
            "architecture": REPO_ROOT / "docs" / "architecture.md",
            "mcp": REPO_ROOT / "docs" / "mcp.md",
            "developer-guide": REPO_ROOT / "docs" / "developer_guide.md",
        }
        target = doc_map.get(doc_id)
        if target is None:
            valid = ", ".join(sorted(doc_map))
            raise ValueError(f"Unknown doc_id '{doc_id}'. Valid ids: {valid}")
        return target.read_text(encoding="utf-8")

    return mcp


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Fileman MCP stdio server.")
    parser.add_argument(
        "--transport",
        choices=("stdio",),
        default=os.environ.get("FILEMAN_MCP_TRANSPORT", "stdio"),
        help="Transport to use. v1 stays stdio-only for local-first clients.",
    )
    parser.add_argument(
        "--print-tools",
        action="store_true",
        help="Print the current MCP v1 tool names and exit.",
    )
    parser.add_argument(
        "--print-resources",
        action="store_true",
        help="Print the current MCP v1 resource URIs and exit.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("FILEMAN_MCP_LOG_LEVEL", "INFO"),
        help="Logging level. Logs stay on stderr so stdout remains reserved for the MCP protocol.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), stream=sys.stderr)
    facade = FilemanMcpApiFacade().start()

    try:
        if args.print_tools:
            for item in facade.get_tool_matrix()["tools"]:
                print(item["name"])
            return

        if args.print_resources:
            for uri in (
                "fileman://workflow/safety-boundary",
                "fileman://workflow/tool-matrix",
                "fileman://jobs/{job_id}/review-queue",
                "fileman://jobs/{job_id}/manifest-view",
                "fileman://jobs/{job_id}/report",
                "fileman://docs/{doc_id}",
            ):
                print(uri)
            return

        server = create_mcp_server(facade)
        server.run(transport=args.transport)
    finally:
        facade.close()


if __name__ == "__main__":
    main()
