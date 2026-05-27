#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject.get("project", {}).get("scripts", {})
    required_entrypoints = pyproject.get("tool", {}).get("fileorganize", {}).get("package_smoke", {}).get("required_entrypoints", [])

    issues: list[str] = []
    if scripts.get("fileorganize-mcp") != "apps.mcp.server:main":
        issues.append("pyproject.toml must expose fileorganize-mcp -> apps.mcp.server:main")
    if "fileorganize-mcp" not in required_entrypoints:
        issues.append("package smoke required_entrypoints must include fileorganize-mcp")
    if not (repo_root / "apps" / "mcp" / "server.py").exists():
        issues.append("apps/mcp/server.py is required for Fileorganize MCP")
    if not (repo_root / "tooling" / "runtime" / "run_mcp_stdio.sh").exists():
        issues.append("tooling/runtime/run_mcp_stdio.sh is required for Fileorganize MCP")
    package_json = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    npm_scripts = package_json.get("scripts", {})
    if npm_scripts.get("mcp:stdio") != "bash tooling/runtime/run_mcp_stdio.sh":
        issues.append("package.json must expose mcp:stdio -> bash tooling/runtime/run_mcp_stdio.sh")

    required_docs = [
        repo_root / "docs" / "mcp.md",
        repo_root / "docs" / "developer_guide.md",
        repo_root / "docs" / "review_first_ai_file_organizer.md",
    ]
    for path in required_docs:
        if not path.exists():
            issues.append(f"required MCP/discoverability doc missing: {path.relative_to(repo_root)}")

    if issues:
        print("❌ check_mcp_surface: surface contract drift detected")
        for item in issues:
            print(f"- {item}")
        return 1

    print("✅ check_mcp_surface: MCP entrypoint surface looks aligned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
