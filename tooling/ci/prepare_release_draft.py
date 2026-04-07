#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _extract_version(pyproject: str) -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, flags=re.MULTILINE)
    if not match:
        raise SystemExit("version not found in pyproject.toml")
    return match.group(1)


def _extract_unreleased(changelog: str) -> str:
    match = re.search(r"## \[Unreleased\]\n(?P<body>.*?)(?:\n## \[|\Z)", changelog, flags=re.DOTALL)
    if not match:
        return "- No unreleased notes captured.\n"
    body = match.group("body").strip()
    return body + ("\n" if not body.endswith("\n") else "")


def _gh_repo_view(repo_root: Path) -> dict[str, object] | None:
    try:
        proc = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner,url,isPrivate,defaultBranchRef"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _git_tags(repo_root: Path) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "tag", "--list"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _platform_gaps(repo_root: Path) -> str:
    repo_view = _gh_repo_view(repo_root)
    tags = _git_tags(repo_root)
    lines: list[str] = []

    if repo_view is not None:
        repo_name = str(repo_view.get("nameWithOwner", "unknown"))
        repo_url = str(repo_view.get("url", "unknown"))
        is_private = bool(repo_view.get("isPrivate", False))
        visibility = "private" if is_private else "public"
        lines.append(f"- Repository: `{repo_name}` ({repo_url})")
        lines.append(f"- Visibility: `{visibility}`")
        if is_private:
            lines.append(
                "- Current release blocker: repo is still private; first public release still requires an intentional visibility switch."
            )
            lines.append(
                "- Branch protection / rulesets API is unavailable on the current "
                "private repo plan without GitHub Pro; re-verify required checks "
                "after visibility changes."
            )
            lines.append(
                "- GitHub Private Vulnerability Reporting is not available on the "
                "current private repo state; `SECURITY.md` fallback is the active path."
            )
    else:
        lines.append("- Repository: `unknown`")
        lines.append("- Visibility: `unknown`")
        lines.append(
            "- GitHub repo metadata was not available from the local environment; "
            "manually confirm visibility, branch protection, and security reporting "
            "before publishing."
        )

    if not tags:
        lines.append(
            "- No git tag exists yet for this release line; create the first release "
            "tag only after final review of release notes and platform settings."
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a GitHub Releases draft template from current repo metadata")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=".runtime-cache/logs/release-draft.md")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    version = _extract_version(pyproject)
    unreleased = _extract_unreleased(changelog)
    platform_gaps = _platform_gaps(repo_root)
    output = repo_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    draft = f"""# Release {version}

## Summary

- Release posture: limited-maintenance open source
- Distribution: GitHub repository + GitHub Releases
- License: MIT

## Verified Gates

- [ ] `bash tooling/docs/check_docs_scope.sh`
- [ ] `bash tooling/docs/docs_smoke.sh --install-smoke`
- [ ] `bash tooling/gates/check_cold_start_rebuild.sh`
- [ ] `bash tooling/gates/verify_repo_final.sh` (repo-side governance scorecard only)
- [ ] `bash tooling/gates/quality_gate.sh` (only delivery-complete signal)
- [ ] `bash tooling/gates/history_secret_scan.sh`
- [ ] `bash tooling/gates/ai_eval_gate.sh`

## Release Notes Seed

{unreleased}

## Platform-side Gaps

{platform_gaps}

## Known Limitations

- No public PyPI publish in this release line
- No public container registry publish in this release line
- CI runtime image provenance is wired, but GitHub Release asset provenance / SBOM are not yet closed in this release line
- Live AI eval depends on valid Gemini credentials and reports explicit skipped/N/A without them

## Platform-side Checklist

- [ ] Current open-source surface files are committed and pushed to the default branch
- [ ] Branch protection required checks align with repository docs
- [ ] `.github/CODEOWNERS` is active on GitHub
- [ ] Private Vulnerability Reporting is enabled, or `SECURITY.md` fallback remains accurate
"""
    output.write_text(draft, encoding="utf-8")
    print(f"release draft written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
