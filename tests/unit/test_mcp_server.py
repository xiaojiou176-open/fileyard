from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from apps.mcp.server import create_mcp_server


def _isolated_runtime_env(tmp_path: Path) -> dict[str, str]:
    workspace_root = tmp_path / "workspace"
    input_root = workspace_root / "data" / "raw"
    output_root = workspace_root / "data" / "organized"
    manifest_root = workspace_root / ".fileorganize" / "manifests"
    artifact_root = workspace_root / ".fileorganize" / "artifacts"
    run_root = workspace_root / ".fileorganize" / "runs"
    for path in (input_root, output_root, manifest_root, artifact_root, run_root):
        path.mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "PYTHONPATH": str(Path.cwd()),
        "FILEORGANIZE_WORKSPACE_ROOT": str(workspace_root),
        "FILEORGANIZE_INPUT_ROOT": str(input_root),
        "FILEORGANIZE_OUTPUT_ROOT": str(output_root),
        "FILEORGANIZE_MANIFEST_ROOT": str(manifest_root),
        "FILEORGANIZE_ARTIFACT_ROOT": str(artifact_root),
        "FILEORGANIZE_RUN_BUNDLE_ROOT": str(run_root),
    }


def test_mcp_catalog_exposes_safe_v1_tools_and_resources(tmp_path: Path) -> None:
    env = _isolated_runtime_env(tmp_path)
    previous_env = {key: os.environ.get(key) for key in env if key.startswith("FILEORGANIZE_")}
    try:
        for key, value in env.items():
            if key.startswith("FILEORGANIZE_"):
                os.environ[key] = value
        server = create_mcp_server()
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    tool_manager = getattr(server, "_tool_manager")
    resource_manager = getattr(server, "_resource_manager")
    tool_names = {tool.name for tool in tool_manager.list_tools()}
    resource_uris = {str(item.uri) for item in resource_manager.list_resources()}

    assert "jobs.list" in tool_names
    assert "review_queue.get" in tool_names
    assert "manifest.patch_row" in tool_names
    assert "apply.preview" in tool_names
    assert "runtime.settings.get" in tool_names
    assert "inbox.analyze" in tool_names
    assert "apply.execute" not in tool_names
    assert "rollback.create" not in tool_names

    assert "fileorganize://workflow/safety-boundary" in resource_uris
    assert "fileorganize://workflow/tool-matrix" in resource_uris


def test_mcp_stdio_supports_initialize_tools_resources_and_safe_read_calls(tmp_path: Path) -> None:
    runtime_env = _isolated_runtime_env(tmp_path)

    async def run() -> None:
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "apps.mcp.server"],
            env=runtime_env,
            cwd=str(Path.cwd()),
        )
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                result = await session.initialize()
                assert result.serverInfo.name == "Fileorganize MCP"

                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                assert "strategy_packs.list" in tool_names
                assert "watch_sources.list" in tool_names
                assert "runtime.settings.get" in tool_names
                assert "apply.execute" not in tool_names

                packs = await session.call_tool("strategy_packs.list")
                assert packs.isError is False
                assert isinstance(packs.structuredContent, dict)
                assert "items" in packs.structuredContent

                runtime_settings = await session.call_tool("runtime.settings.get")
                assert runtime_settings.isError is False
                assert isinstance(runtime_settings.structuredContent, dict)
                assert "workspace_root" in runtime_settings.structuredContent

                resources = await session.list_resources()
                resource_uris = {str(resource.uri) for resource in resources.resources}
                assert "fileorganize://workflow/safety-boundary" in resource_uris

                safety = await session.read_resource("fileorganize://workflow/safety-boundary")
                assert safety.contents
                assert "review-first" in safety.contents[0].text

                tool_matrix = await session.read_resource("fileorganize://workflow/tool-matrix")
                assert tool_matrix.contents
                assert "inbox.analyze" in tool_matrix.contents[0].text

                resource_templates = await session.list_resource_templates()
                template_uris = {template.uriTemplate for template in resource_templates.resourceTemplates}
                assert "fileorganize://docs/{doc_id}" in template_uris

                docs_resource = await session.read_resource("fileorganize://docs/mcp")
                assert docs_resource.contents
                assert "Fileorganize MCP v1" in docs_resource.contents[0].text

    asyncio.run(run())
