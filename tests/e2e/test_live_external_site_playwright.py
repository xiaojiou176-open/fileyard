import ipaddress
import os
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import pytest

LIVE_FLAG = "FILEYARD_RUN_LIVE_TESTS"
LIVE_MAX_RETRIES = 2
LIVE_BROWSER_GOTO_TIMEOUT_MS = int(os.getenv("LIVE_BROWSER_GOTO_TIMEOUT_MS", "60000"))
DEFAULT_LIVE_TEST_URL = "https://docs.github.com/en"
_BLOCKED_HOSTS = {
    "example.com",
    "www.example.com",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
}
_BLOCKED_SUFFIXES = (".local", ".localhost", ".test", ".invalid", ".example")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_runtime_env_value(name: str) -> str:
    workspace_root = Path(os.getenv("FILEYARD_WORKSPACE_ROOT", "~/.fileyard/workspaces/default")).expanduser()
    env_path = workspace_root / ".fileyard" / "env" / "runtime.env"
    if not env_path.exists():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value.strip()
    return ""


def resolve_live_var(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    if value:
        os.environ[name] = value
        return value
    value = _read_runtime_env_value(name)
    if value:
        os.environ[name] = value
        return value
    return default


def _is_live_enabled() -> bool:
    return resolve_live_var(LIVE_FLAG, "0").strip() == "1"


@pytest.fixture(autouse=True)
def _restore_live_env_vars():
    keys = (LIVE_FLAG, "FILEYARD_LIVE_TEST_URL")
    snapshot = {key: os.environ.get(key) for key in keys}
    yield
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _host_is_real_external(host: str) -> bool:
    normalized = host.strip().strip(".").lower()
    if not normalized:
        return False
    if normalized in _BLOCKED_HOSTS:
        return False
    if normalized.endswith(_BLOCKED_SUFFIXES):
        return False
    try:
        addr = ipaddress.ip_address(normalized)
    except ValueError:
        return True
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified)


def _live_browser_url() -> str:
    url = resolve_live_var("FILEYARD_LIVE_TEST_URL", DEFAULT_LIVE_TEST_URL).strip()
    if not url:
        pytest.fail("live_browser preflight failed: FILEYARD_LIVE_TEST_URL is required and must point to a real external site")
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not parsed.netloc:
        pytest.fail(f"live_browser preflight failed: FILEYARD_LIVE_TEST_URL must be an absolute https URL, got {url!r}")
    if not _host_is_real_external(host):
        pytest.fail(f"live_browser preflight failed: FILEYARD_LIVE_TEST_URL must target a real external host, got host={host!r}")
    return url


def _classify_live_browser_error(exc: BaseException | None, status: int | None) -> str:
    if status is not None:
        if status >= 500:
            return "network-timeout"
        if status in (408, 425, 429):
            return "network-timeout"
        if status >= 400:
            return "business"
    if exc is None:
        return "business"
    detail = f"{type(exc).__name__}: {exc}".lower()
    network_hints = (
        "timeout",
        "timed out",
        "net::",
        "net::err_aborted",
        "err_network_changed",
        "err_name_not_resolved",
        "name resolution",
        "connection",
        "dns",
        "econn",
        "reset",
        "unreachable",
        "chrome-error://chromewebdata",
        "interrupted by another navigation",
        "navigation interrupted",
        "navigation failed because page was closed",
        "target closed",
        "browser has been closed",
        "target page, context or browser has been closed",
        "execution context was destroyed",
    )
    if any(token in detail for token in network_hints):
        return "network-timeout"
    return "business"


@pytest.fixture
def live_cleanup_actions():
    actions: list[tuple[str, Callable[[], None]]] = []
    yield actions
    failures: list[str] = []
    for label, callback in reversed(actions):
        try:
            callback()
        except Exception as exc:  # pragma: no cover - env-dependent branch
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
    if failures:
        pytest.fail("live_browser teardown failed: " + "; ".join(failures))


@pytest.mark.live_browser
def test_live_browser_env_preflight():
    # test-quality: allow-no-assert
    if not _is_live_enabled():
        pytest.skip(f"set {LIVE_FLAG}=1 to run live browser tests")
    _live_browser_url()


@pytest.mark.live_browser
def test_live_external_site_with_playwright(live_cleanup_actions):
    if not _is_live_enabled():
        pytest.skip(f"set {LIVE_FLAG}=1 to run live browser tests")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - env-dependent branch
        pytest.fail(f"live_browser enabled but playwright is unavailable: {exc}")
    url = _live_browser_url()

    # Read-only live policy: if a future live test writes externally, it must register teardown.
    assert not live_cleanup_actions

    with sync_playwright() as p:
        last_error: str | None = None
        for attempt in range(1, LIVE_MAX_RETRIES + 1):
            browser = None
            context = None
            response = None
            captured_exc: BaseException | None = None
            try:
                # Launch a fresh browser per attempt so a transient Chromium crash
                # does not poison the retry path itself.
                browser = p.chromium.launch(headless=True)
                # Use the default browser fingerprint so the live probe matches a normal Chromium session.
                context = browser.new_context()
                page = context.new_page()
                response = page.goto(
                    url,
                    wait_until="commit",
                    timeout=LIVE_BROWSER_GOTO_TIMEOUT_MS,
                )
                if response is None:
                    raise RuntimeError(f"live_browser got no response for {url}")
                if response.status >= 500:
                    raise RuntimeError(
                        f"live_browser server error for {url}: status={response.status} status_text={response.status_text!r}"
                    )
                assert response.ok, f"live_browser request not ok for {url}: status={response.status} status_text={response.status_text!r}"

                # The external live probe is an egress/browser reachability check,
                # not a contract test for a third-party page's DOM timing.
                content_type = (response.header_value("content-type") or "").lower()
                assert "text/html" in content_type, f"live_browser expected HTML content for {url}: content_type={content_type!r}"
                final_url = (page.url or "").strip()
                assert final_url.startswith("https://"), f"live_browser final url must stay https for {url}: {final_url!r}"
                break
            except Exception as exc:  # pragma: no cover - env-dependent branch
                captured_exc = exc
                status = response.status if response is not None else None
                category = _classify_live_browser_error(captured_exc, status)
                last_error = (
                    f"live_browser attempt={attempt}/{LIVE_MAX_RETRIES} LIVE_ERROR_CLASS={category} detail={type(exc).__name__}: {exc}"
                )
                if category != "network-timeout" or attempt >= LIVE_MAX_RETRIES:
                    pytest.fail(last_error)
            finally:
                if context is not None:
                    context.close()
                if browser is not None:
                    browser.close()
        else:  # pragma: no cover - defensive
            pytest.fail(last_error or "live_browser failed with unknown error")
