#!/usr/bin/env python3
"""GitHub platform gate for release/quality_gate public-readiness checks."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml  # type: ignore[import-untyped]


def _load_policy(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid public readiness policy: {path}")
    return payload


def _load_optional_allowlist(root: Path, policy: dict) -> set[str]:
    raw_path = str(policy.get("accepted_code_scanning_rules_contract", "")).strip()
    if not raw_path:
        return set()
    allowlist_path = (root / raw_path).resolve()
    if not allowlist_path.exists():
        return set()
    payload = yaml.safe_load(allowlist_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid code-scanning allowlist: {allowlist_path}")
    rows = payload.get("accepted_rule_ids", [])
    if not isinstance(rows, list):
        raise SystemExit("invalid code-scanning allowlist: accepted_rule_ids must be a list")
    return {str(item).strip() for item in rows if str(item).strip()}


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)
    except OSError:
        return None


def _count_alerts(proc: subprocess.CompletedProcess[str] | None) -> int | None:
    if proc is None or proc.returncode != 0:
        return None
    text = proc.stdout.strip()
    if not text:
        return 0
    payload = json.loads(text)
    if isinstance(payload, list):
        return len(payload)
    raise SystemExit("invalid GitHub alerts payload: expected a list")


def _load_alerts(proc: subprocess.CompletedProcess[str] | None) -> list[dict] | None:
    if proc is None or proc.returncode != 0:
        return None
    text = proc.stdout.strip()
    if not text:
        return []
    payload = json.loads(text)
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    raise SystemExit("invalid GitHub alerts payload: expected a list")


def _extract_code_scanning_rule_id(alert: dict) -> str:
    for candidate in (
        alert.get("rule_id"),
        alert.get("ruleId"),
        (alert.get("rule") or {}).get("id") if isinstance(alert.get("rule"), dict) else None,
        ((alert.get("tool") or {}).get("rule") or {}).get("id")
        if isinstance(alert.get("tool"), dict) and isinstance((alert.get("tool") or {}).get("rule"), dict)
        else None,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Check GitHub platform state for public/open-source readiness")
    parser.add_argument("--root", default=".")
    parser.add_argument("--policy", default="contracts/governance/public_readiness_policy.yaml")
    parser.add_argument("--mode", choices=("repo", "release"), default="repo")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    policy = _load_policy(root / args.policy)
    accepted_code_scanning_rules = _load_optional_allowlist(root, policy)
    release_policy = policy.get("release_mode", {})
    if not isinstance(release_policy, dict):
        raise SystemExit("invalid public readiness policy: release_mode must be a mapping")

    default_branch = str(policy.get("default_branch", "main"))
    issues: list[str] = []
    payload: dict[str, object] = {
        "mode": args.mode,
        "repo_view_available": False,
        "name_with_owner": None,
        "is_private": None,
        "viewer_permission": None,
        "default_branch": default_branch,
        "pvr_status_code": None,
        "branch_protection_status_code": None,
        "code_scanning_status_code": None,
        "secret_scanning_status_code": None,
        "code_scanning_open_alerts": None,
        "accepted_code_scanning_rule_ids": sorted(accepted_code_scanning_rules),
        "accepted_code_scanning_open_alerts": None,
        "blocking_code_scanning_open_alerts": None,
        "secret_scanning_open_alerts": None,
        "platform_query_state": "unknown",
        "issues": issues,
    }

    repo_view_proc = _run(["gh", "repo", "view", "--json", "nameWithOwner,isPrivate,defaultBranchRef,viewerPermission"], root)
    if repo_view_proc is None or repo_view_proc.returncode != 0:
        if args.mode == "release":
            issues.append("GitHub repo metadata unavailable; release mode requires authenticated `gh repo view` access")
    else:
        repo_view = json.loads(repo_view_proc.stdout)
        if isinstance(repo_view, dict):
            payload["repo_view_available"] = True
            payload["name_with_owner"] = repo_view.get("nameWithOwner")
            payload["is_private"] = repo_view.get("isPrivate")
            payload["viewer_permission"] = repo_view.get("viewerPermission")
            branch = repo_view.get("defaultBranchRef")
            if isinstance(branch, dict):
                payload["default_branch"] = branch.get("name", default_branch)

        if args.mode == "release" and bool(release_policy.get("require_public_repo", False)) and payload["is_private"] is True:
            issues.append("release mode requires a public repository; current GitHub repo is still private")

        repo_name = payload.get("name_with_owner")
        if isinstance(repo_name, str) and repo_name:
            pvr_proc = _run(["gh", "api", f"repos/{repo_name}/private-vulnerability-reporting"], root)
            branch_proc = _run(["gh", "api", f"repos/{repo_name}/branches/{payload['default_branch']}/protection"], root)
            code_scanning_proc = _run(["gh", "api", f"repos/{repo_name}/code-scanning/alerts?state=open&per_page=100"], root)
            secret_scanning_proc = _run(["gh", "api", f"repos/{repo_name}/secret-scanning/alerts?state=open&per_page=100"], root)
            payload["pvr_status_code"] = None if pvr_proc is None else pvr_proc.returncode
            payload["branch_protection_status_code"] = None if branch_proc is None else branch_proc.returncode
            payload["code_scanning_status_code"] = None if code_scanning_proc is None else code_scanning_proc.returncode
            payload["secret_scanning_status_code"] = None if secret_scanning_proc is None else secret_scanning_proc.returncode
            payload["code_scanning_open_alerts"] = _count_alerts(code_scanning_proc)
            payload["secret_scanning_open_alerts"] = _count_alerts(secret_scanning_proc)
            code_scanning_alerts = _load_alerts(code_scanning_proc)
            if code_scanning_alerts is not None:
                accepted_count = 0
                blocking_count = 0
                for alert in code_scanning_alerts:
                    rule_id = _extract_code_scanning_rule_id(alert)
                    if rule_id and rule_id in accepted_code_scanning_rules:
                        accepted_count += 1
                    else:
                        blocking_count += 1
                payload["accepted_code_scanning_open_alerts"] = accepted_count
                payload["blocking_code_scanning_open_alerts"] = blocking_count
            viewer_permission = str(payload.get("viewer_permission") or "").upper()
            limited_permission = viewer_permission in {"READ", "TRIAGE", ""}

            if args.mode == "release" and bool(release_policy.get("require_pvr", False)):
                if pvr_proc is None or pvr_proc.returncode != 0:
                    payload["platform_query_state"] = (
                        "query-blocked-permission-context" if limited_permission else "misconfigured-or-unavailable"
                    )
                    if limited_permission:
                        issues.append(
                            "release mode requires GitHub Private Vulnerability Reporting to be queryable; "
                            f"current viewer permission is {viewer_permission or 'UNKNOWN'}"
                        )
                    else:
                        issues.append("release mode requires GitHub Private Vulnerability Reporting to be accessible")
            if args.mode == "release" and bool(release_policy.get("require_branch_protection", False)):
                if branch_proc is None or branch_proc.returncode != 0:
                    payload["platform_query_state"] = (
                        "query-blocked-permission-context" if limited_permission else "misconfigured-or-unavailable"
                    )
                    if limited_permission:
                        issues.append(
                            "release mode requires branch protection / required checks to be queryable on GitHub; "
                            f"current viewer permission is {viewer_permission or 'UNKNOWN'}"
                        )
                    else:
                        issues.append(
                            "release mode requires branch protection / required checks to be queryable on GitHub; "
                            "the current platform state appears misconfigured or unavailable"
                        )
                elif payload["platform_query_state"] == "unknown":
                    payload["platform_query_state"] = "queryable-and-aligned"
            if args.mode == "release" and bool(release_policy.get("require_zero_code_scanning_alerts", False)):
                code_scanning_open_alerts = payload.get("code_scanning_open_alerts")
                if code_scanning_open_alerts is None:
                    payload["platform_query_state"] = (
                        "query-blocked-permission-context" if limited_permission else "misconfigured-or-unavailable"
                    )
                    if limited_permission:
                        issues.append(
                            "release mode requires GitHub code scanning alerts to be queryable; "
                            f"current viewer permission is {viewer_permission or 'UNKNOWN'}"
                        )
                    else:
                        issues.append("release mode requires GitHub code scanning alerts to be queryable")
                elif isinstance(payload.get("blocking_code_scanning_open_alerts"), int):
                    if int(payload["blocking_code_scanning_open_alerts"]) > 0:
                        issues.append("release mode requires zero open GitHub code scanning alerts outside the accepted-exception contract")
                elif isinstance(code_scanning_open_alerts, int) and code_scanning_open_alerts > 0:
                    issues.append("release mode requires zero open GitHub code scanning alerts")
            if args.mode == "release" and bool(release_policy.get("require_zero_secret_scanning_alerts", False)):
                secret_scanning_open_alerts = payload.get("secret_scanning_open_alerts")
                if secret_scanning_open_alerts is None:
                    payload["platform_query_state"] = (
                        "query-blocked-permission-context" if limited_permission else "misconfigured-or-unavailable"
                    )
                    if limited_permission:
                        issues.append(
                            "release mode requires GitHub secret scanning alerts to be queryable; "
                            f"current viewer permission is {viewer_permission or 'UNKNOWN'}"
                        )
                    else:
                        issues.append("release mode requires GitHub secret scanning alerts to be queryable")
                elif isinstance(secret_scanning_open_alerts, int) and secret_scanning_open_alerts > 0:
                    issues.append("release mode requires zero open GitHub secret scanning alerts")

    if args.json_out:
        out_path = (root / args.json_out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if issues:
        print("❌ public-platform-state: failed")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("✅ public-platform-state: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
