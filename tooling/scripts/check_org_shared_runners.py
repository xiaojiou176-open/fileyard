#!/usr/bin/env python3
"""Validate org shared self-hosted runner inventory for CI bootstrap.

This runner-bootstrap check is part of the same governance surface enforced by
the repository pre-push and quality_gate lanes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

RATE_LIMIT_MAX_RETRIES = 5
MIN_ONLINE_RUNNERS = 12
REQUIRED_LABEL = "shared-pool"


def _http_error_body(exc: urllib.error.HTTPError) -> str:
    body = getattr(exc, "_cached_body", None)
    if isinstance(body, str):
        return body
    raw = exc.read().decode("utf-8", errors="ignore")
    setattr(exc, "_cached_body", raw)
    return raw


def _rate_limit_wait_seconds(exc: urllib.error.HTTPError) -> int:
    if exc.code != 403:
        return 0
    body = _http_error_body(exc).lower()
    if "rate limit exceeded" not in body:
        return 0
    retry_after = exc.headers.get("Retry-After", "").strip()
    if retry_after.isdigit():
        return max(1, int(retry_after))
    reset_epoch = exc.headers.get("X-RateLimit-Reset", "").strip()
    if reset_epoch.isdigit():
        return max(1, int(reset_epoch) - int(time.time()) + 1)
    return 30


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help="GitHub organization name.")
    parser.add_argument(
        "--token",
        default="",
        help="GitHub token with permission to read organization runners.",
    )
    return parser.parse_args(argv)


def _api_get(url: str, token: str) -> dict[str, object]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "fileorganize-ci-runner-bootstrap",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
        return json.loads(resp.read().decode("utf-8"))


def _list_org_runners(org: str, token: str) -> list[dict[str, object]]:
    runners: list[dict[str, object]] = []
    page = 1
    total_count: int | None = None
    encoded_org = urllib.parse.quote(org, safe="")
    rate_limit_retries = 0

    while True:
        url = f"https://api.github.com/orgs/{encoded_org}/actions/runners?per_page=100&page={page}"
        try:
            payload = _api_get(url, token)
            rate_limit_retries = 0
        except urllib.error.HTTPError as exc:
            wait_s = _rate_limit_wait_seconds(exc)
            if wait_s <= 0 or rate_limit_retries >= RATE_LIMIT_MAX_RETRIES:
                raise
            rate_limit_retries += 1
            print(
                f"⚠️ runner-bootstrap: GitHub API rate limited on page={page}; "
                f"retry {rate_limit_retries}/{RATE_LIMIT_MAX_RETRIES} after {wait_s}s"
            )
            time.sleep(wait_s)
            continue
        if total_count is None:
            raw_total = payload.get("total_count")
            if isinstance(raw_total, int):
                total_count = raw_total
        raw_runners = payload.get("runners")
        if not isinstance(raw_runners, list):
            raise ValueError("API response missing 'runners' list.")
        runners.extend(item for item in raw_runners if isinstance(item, dict))

        # Stop at final page.
        if len(raw_runners) < 100:
            break
        if total_count is not None and len(runners) >= total_count:
            break
        page += 1

    return runners


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    token = args.token or os.getenv("ORG_RUNNER_AUDIT_TOKEN", "") or os.getenv("GH_TOKEN", "")
    if not token:
        print("❌ runner-bootstrap: missing token (use --token or ORG_RUNNER_AUDIT_TOKEN/GH_TOKEN).")
        return 2

    try:
        raw_runners = _list_org_runners(args.org, token)
    except urllib.error.HTTPError as exc:
        body = _http_error_body(exc)
        print(f"❌ runner-bootstrap: GitHub API HTTP {exc.code}: {body}")
        return 2
    except ValueError as exc:
        print(f"❌ runner-bootstrap: {exc}")
        return 2
    except Exception as exc:  # pragma: no cover
        print(f"❌ runner-bootstrap: GitHub API request failed: {exc}")
        return 2

    runners: dict[str, dict[str, object]] = {}
    for item in raw_runners:
        if not isinstance(item, dict):
            continue
        if not has_required_label(item, REQUIRED_LABEL):
            continue
        name = str(item.get("name", "")).strip()
        if name:
            runners[name] = item

    actual_names = set(runners.keys())
    if not actual_names:
        print(f"❌ runner-bootstrap: no organization runners matched required label `{REQUIRED_LABEL}`.")
        return 1

    offline = sorted(name for name, item in runners.items() if str(item.get("status", "")).lower() != "online")
    online_count = len(actual_names) - len(offline)
    if online_count < MIN_ONLINE_RUNNERS:
        print(
            "❌ runner-bootstrap: shared runner pool is below minimum online capacity "
            f"({online_count}/{len(actual_names)} online, require >= {MIN_ONLINE_RUNNERS})."
        )
        print(f"offline={offline}")
        return 1

    print(
        "✅ runner-bootstrap: shared-pool runner inventory verified by label and capacity "
        f"({len(actual_names)} runners, online={online_count}, minimum={MIN_ONLINE_RUNNERS})."
    )
    for name in sorted(actual_names):
        labels = item_labels(runners[name])
        print(f"- {name}: online labels={labels}")
    return 0


def item_labels(item: dict[str, object]) -> str:
    raw = item.get("labels")
    if not isinstance(raw, list):
        return "[]"
    names: list[str] = []
    for entry in raw:
        if isinstance(entry, dict):
            label_name = str(entry.get("name", "")).strip()
            if label_name:
                names.append(label_name)
    return str(sorted(names))


def has_required_label(item: dict[str, object], required_label: str) -> bool:
    raw = item.get("labels")
    if not isinstance(raw, list):
        return False
    for entry in raw:
        if isinstance(entry, dict) and str(entry.get("name", "")).strip() == required_label:
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
