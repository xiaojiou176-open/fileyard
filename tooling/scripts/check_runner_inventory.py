#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate GitHub Actions runner inventory against a label/capacity contract.")
    parser.add_argument("--org", default="", help="GitHub organization name. Optional in --mock mode.")
    parser.add_argument("--token-env", default="ORG_RUNNER_AUDIT_TOKEN", help="Environment variable containing GitHub API token.")
    parser.add_argument("--min-online", type=int, default=12, help="Minimum number of matching online runners.")
    parser.add_argument(
        "--required-label",
        action="append",
        default=[],
        help="Required runner label. Can be passed multiple times.",
    )
    parser.add_argument("--mock", action="store_true", help="Use an in-memory sample payload instead of GitHub API.")
    parser.add_argument("--mock-file", default="", help="Optional JSON file to use with --mock.")
    return parser.parse_args()


def _http_error_body(exc: urllib.error.HTTPError) -> str:
    raw = exc.read().decode("utf-8", errors="ignore")
    setattr(exc, "_cached_body", raw)
    return raw


def _rate_limit_wait_seconds(exc: urllib.error.HTTPError) -> int:
    if exc.code != 403:
        return 0
    body = getattr(exc, "_cached_body", None) or _http_error_body(exc)
    if "rate limit exceeded" not in body.lower():
        return 0
    retry_after = exc.headers.get("Retry-After", "").strip()
    if retry_after.isdigit():
        return max(1, int(retry_after))
    reset_epoch = exc.headers.get("X-RateLimit-Reset", "").strip()
    if reset_epoch.isdigit():
        return max(1, int(reset_epoch) - int(time.time()) + 1)
    return 30


def _api_get(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "fileorganize-ci-runner-inventory",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
        return json.loads(resp.read().decode("utf-8"))


def _list_org_runners(org: str, token: str) -> list[dict[str, Any]]:
    runners: list[dict[str, Any]] = []
    page = 1
    total_count: int | None = None
    encoded_org = urllib.parse.quote(org, safe="")
    retries = 0
    while True:
        url = f"https://api.github.com/orgs/{encoded_org}/actions/runners?per_page=100&page={page}"
        try:
            payload = _api_get(url, token)
            retries = 0
        except urllib.error.HTTPError as exc:
            wait_s = _rate_limit_wait_seconds(exc)
            if wait_s <= 0 or retries >= 5:
                raise
            retries += 1
            print(f"⚠️ runner_inventory: GitHub API rate limited on page={page}; retry {retries}/5 after {wait_s}s")
            time.sleep(wait_s)
            continue
        if total_count is None and isinstance(payload.get("total_count"), int):
            total_count = payload["total_count"]
        raw_runners = payload.get("runners")
        if not isinstance(raw_runners, list):
            raise ValueError("GitHub API response missing 'runners' list")
        runners.extend(item for item in raw_runners if isinstance(item, dict))
        if len(raw_runners) < 100:
            break
        if total_count is not None and len(runners) >= total_count:
            break
        page += 1
    return runners


def _load_mock_payload(mock_file: str) -> list[dict[str, Any]]:
    if mock_file:
        with open(mock_file, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, list):
            raise SystemExit("mock payload must be a list of runner objects")
        return [item for item in payload if isinstance(item, dict)]

    sample: list[dict[str, Any]] = []
    for idx in range(1, 16):
        sample.append(
            {
                "name": f"shared-runner-{idx:02d}",
                "status": "online" if idx <= 13 else "offline",
                "labels": [
                    {"name": "self-hosted"},
                    {"name": "shared-pool"},
                    {"name": "linux"},
                ],
            }
        )
    return sample


def _runner_labels(runner: dict[str, Any]) -> set[str]:
    labels = runner.get("labels", [])
    if not isinstance(labels, list):
        return set()
    result: set[str] = set()
    for item in labels:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
        else:
            name = str(item).strip()
        if name:
            result.add(name)
    return result


def main() -> int:
    args = _parse_args()
    required_labels = {label.strip() for label in args.required_label if label.strip()}

    if args.mock:
        raw_runners = _load_mock_payload(args.mock_file)
        source = "mock"
    else:
        if not args.org.strip():
            print("❌ runner_inventory: --org is required unless --mock is used")
            return 2
        token = os.environ.get(args.token_env, "").strip() or os.environ.get("GITHUB_TOKEN", "").strip()
        if not token:
            print(f"❌ runner_inventory: missing token env {args.token_env}/GITHUB_TOKEN")
            return 2
        try:
            raw_runners = _list_org_runners(args.org.strip(), token)
        except urllib.error.HTTPError as exc:
            print(f"❌ runner_inventory: GitHub API HTTP {exc.code}: {_http_error_body(exc)}")
            return 2
        except Exception as exc:  # noqa: BLE001
            print(f"❌ runner_inventory: GitHub API request failed: {exc}")
            return 2
        source = f"org={args.org.strip()}"

    matching = []
    for runner in raw_runners:
        labels = _runner_labels(runner)
        if required_labels and not required_labels.issubset(labels):
            continue
        matching.append(runner)

    online = sorted(str(item.get("name", "")).strip() for item in matching if str(item.get("status", "")).lower() == "online")
    offline = sorted(str(item.get("name", "")).strip() for item in matching if str(item.get("status", "")).lower() != "online")

    print(
        "runner_inventory: "
        f"source={source} required_labels={sorted(required_labels)} "
        f"matching_total={len(matching)} online={len(online)} offline={len(offline)}"
    )
    if online:
        print(f"online={online}")
    if offline:
        print(f"offline={offline}")

    if len(online) < args.min_online:
        print(f"❌ runner_inventory: matching online runner capacity below threshold (online={len(online)} required={args.min_online})")
        return 1

    print("✅ runner_inventory: capacity contract satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
