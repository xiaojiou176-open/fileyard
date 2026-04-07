from __future__ import annotations

import importlib.util
import io
import urllib.error
from email.message import Message
from pathlib import Path


def _load_module():
    script_path = Path(__file__).resolve().parents[2] / "tooling" / "scripts" / "check_org_shared_runners.py"
    spec = importlib.util.spec_from_file_location("check_org_shared_runners", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_list_org_runners_fetches_all_pages(monkeypatch) -> None:
    module = _load_module()
    seen_urls: list[str] = []

    def fake_api_get(url: str, token: str) -> dict[str, object]:
        seen_urls.append(url)
        if url.endswith("page=1"):
            return {
                "total_count": 101,
                "runners": [{"name": f"runner-{idx}", "status": "online"} for idx in range(100)],
            }
        if url.endswith("page=2"):
            return {
                "total_count": 101,
                "runners": [{"name": "runner-100", "status": "online"}],
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(module, "_api_get", fake_api_get)

    runners = module._list_org_runners("demo-org", "token")

    assert len(runners) == 101
    assert seen_urls == [
        "https://api.github.com/orgs/demo-org/actions/runners?per_page=100&page=1",
        "https://api.github.com/orgs/demo-org/actions/runners?per_page=100&page=2",
    ]


def test_main_rejects_runner_name_set_mismatch(monkeypatch, capsys) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "_list_org_runners",
        lambda org, token: [
            {"name": "unrelated-runner-01", "status": "online", "labels": [{"name": "other"}]},
            {"name": "unrelated-runner-02", "status": "online", "labels": [{"name": "not-shared-pool"}]},
        ],
    )

    rc = module.main(["--org", "demo-org", "--token", "token"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "no organization runners matched required label" in out


def test_list_org_runners_retries_after_rate_limit(monkeypatch, capsys) -> None:
    module = _load_module()
    seen_calls = 0

    def fake_api_get(url: str, token: str) -> dict[str, object]:
        nonlocal seen_calls
        seen_calls += 1
        if seen_calls == 1:
            headers = Message()
            headers["X-RateLimit-Reset"] = "1"
            raise urllib.error.HTTPError(
                url,
                403,
                "rate limited",
                headers,
                io.BytesIO(b'{"message":"API rate limit exceeded"}'),
            )
        return {
            "total_count": 12,
            "runners": [
                {"name": f"temp-shared-pool-{idx:02d}", "status": "online", "labels": [{"name": "shared-pool"}]} for idx in range(1, 13)
            ],
        }

    monkeypatch.setattr(module, "_api_get", fake_api_get)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(module.time, "time", lambda: 0)

    runners = module._list_org_runners("demo-org", "token")
    out = capsys.readouterr().out

    assert len(runners) == 12
    assert seen_calls == 2
    assert "rate limited on page=1" in out


def test_main_allows_limited_offline_runners_when_capacity_remains(monkeypatch, capsys) -> None:
    module = _load_module()
    offline = {"temp-shared-pool-13", "temp-shared-pool-14"}

    monkeypatch.setattr(
        module,
        "_list_org_runners",
        lambda org, token: [
            {
                "name": f"temp-shared-pool-{idx:02d}",
                "status": "offline" if f"temp-shared-pool-{idx:02d}" in offline else "online",
                "labels": [{"name": "shared-pool"}],
            }
            for idx in range(1, 15)
        ],
    )

    rc = module.main(["--org", "demo-org", "--token", "token"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "minimum=" in out
    assert "online=12" in out


def test_main_rejects_runner_pool_below_minimum_online_capacity(monkeypatch, capsys) -> None:
    module = _load_module()
    offline = {"temp-shared-pool-10", "temp-shared-pool-11", "temp-shared-pool-12"}

    monkeypatch.setattr(
        module,
        "_list_org_runners",
        lambda org, token: [
            {
                "name": f"temp-shared-pool-{idx:02d}",
                "status": "offline" if f"temp-shared-pool-{idx:02d}" in offline else "online",
                "labels": [{"name": "shared-pool"}],
            }
            for idx in range(1, 13)
        ],
    )

    rc = module.main(["--org", "demo-org", "--token", "token"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "below minimum online capacity" in out
    assert f"require >= {module.MIN_ONLINE_RUNNERS}" in out
