from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_live_browser_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "tests" / "e2e" / "test_live_external_site_playwright.py"
    spec = importlib.util.spec_from_file_location("live_external_site_playwright", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classify_closed_browser_as_retryable_network_timeout() -> None:
    live_browser = _load_live_browser_module()
    category = live_browser._classify_live_browser_error(
        RuntimeError("Browser.new_context: Target page, context or browser has been closed"),
        None,
    )
    assert category == "network-timeout"


def test_classify_http_404_as_business_error() -> None:
    live_browser = _load_live_browser_module()
    category = live_browser._classify_live_browser_error(None, 404)
    assert category == "business"
