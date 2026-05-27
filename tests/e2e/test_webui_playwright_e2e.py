from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

WAIT_TIMEOUT_S = 180
UPLOAD_ANALYZE_WAIT_TIMEOUT_S = 420
READY_TIMEOUT_S = 60
POLL_INTERVAL_S = 0.3
_WEBUI_DIST_READY = False
_PLAYWRIGHT_BROWSER_READY = False
_MISSING_WEBUI_TOOLING_RE = re.compile(
    r"(?:\b(?:tsc|vite): (?:command )?not found\b"
    r"|TS2307: Cannot find module '@tanstack/react-table'"
    r"|TS7016: Could not find a declaration file for module 'react(?:/jsx-runtime)?')"
)


def _heartbeat(message: str) -> None:
    print(f"[webui-e2e] {message}", flush=True)


@pytest.fixture(autouse=True)
def _reset_non_live_webui_dist_ready() -> None:
    global _WEBUI_DIST_READY
    _WEBUI_DIST_READY = False
    yield


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _workspace_input_root() -> Path:
    return Path(os.environ.get("MOVI_INPUT_ROOT", "~/.fileyard/workspaces/default/data/raw")).expanduser()


def _workspace_output_root() -> Path:
    return Path(os.environ.get("MOVI_OUTPUT_ROOT", "~/.fileyard/workspaces/default/data/organized")).expanduser()


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _is_port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _http_status(url: str) -> int:
    for candidate in _loopback_url_variants(url):
        try:
            with urlopen(candidate, timeout=5) as response:
                return int(response.status)
        except HTTPError as exc:
            return int(exc.code)
        except (URLError, OSError, TimeoutError):
            continue
    return 0


def _loopback_url_variants(url: str) -> list[str]:
    variants = [url]
    if "://127.0.0.1" in url:
        variants.append(url.replace("://127.0.0.1", "://localhost", 1))
    elif "://localhost" in url:
        variants.append(url.replace("://localhost", "://127.0.0.1", 1))
    return variants


def _is_transient_network_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "can't assign requested address",
        "connection reset",
        "connection refused",
        "timed out",
        "temporarily unavailable",
        "address invalid",
    )
    return any(marker in text for marker in markers)


def _build_log_indicates_missing_webui_tooling(log_tail: str) -> bool:
    return bool(_MISSING_WEBUI_TOOLING_RE.search(log_tail))


def _webui_dependencies_ready(repo_root: Path, run_env: dict[str, str]) -> bool:
    vite_bin = repo_root / "apps" / "webui" / "node_modules" / ".bin" / "vite"
    if not vite_bin.exists():
        return False
    proc = subprocess.run(
        ["npm", "--prefix", "apps/webui", "ls", "--depth=0"],
        cwd=repo_root,
        env=run_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    return proc.returncode == 0


def _http_json(url: str) -> dict | list:
    last_error: Exception | None = None
    for _ in range(20):
        for candidate in _loopback_url_variants(url):
            try:
                with urlopen(candidate, timeout=10) as response:
                    payload = response.read().decode("utf-8")
                    return json.loads(payload)
            except (HTTPError, URLError, OSError, TimeoutError) as exc:
                last_error = exc
        sleep_s = 0.5 if (last_error is not None and _is_transient_network_error(last_error)) else POLL_INTERVAL_S
        time.sleep(sleep_s)
    assert last_error is not None
    raise last_error


def _http_json_request(url: str, *, method: str, payload: dict) -> dict | list:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for _ in range(8):
        for candidate in _loopback_url_variants(url):
            request = Request(candidate, data=body, method=method, headers={"Content-Type": "application/json"})
            try:
                with urlopen(request, timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise AssertionError(f"{method} {candidate} failed: status={exc.code} body={detail}") from exc
            except (URLError, OSError, TimeoutError) as exc:
                last_error = exc
        sleep_s = 0.5 if (last_error is not None and _is_transient_network_error(last_error)) else POLL_INTERVAL_S
        time.sleep(sleep_s)
    if last_error is not None:
        raise AssertionError(f"{method} {url} failed after loopback retries: {last_error}") from last_error
    raise AssertionError(f"{method} {url} failed for unknown reason")


def _wait_http_ready(url: str, timeout_s: int, name: str) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _http_status(url)
        if 200 <= status < 400:
            return
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"{name} not ready within {timeout_s}s: {url}")


def _wait_for_job(
    api_base: str,
    predicate: Callable[[dict], bool],
    *,
    timeout_s: int = WAIT_TIMEOUT_S,
    label: str,
) -> dict:
    deadline = time.time() + timeout_s
    last_observed: dict | None = None
    while time.time() < deadline:
        try:
            payload = _http_json(f"{api_base}/api/jobs")
        except (URLError, OSError):
            time.sleep(POLL_INTERVAL_S)
            continue
        assert isinstance(payload, list)
        for item in payload:
            if isinstance(item, dict):
                last_observed = item
            if isinstance(item, dict) and predicate(item):
                return item
        time.sleep(POLL_INTERVAL_S)
    detail = ""
    if isinstance(last_observed, dict):
        detail = (
            f" last_observed_id={last_observed.get('id')!r}"
            f" status={last_observed.get('status')!r}"
            f" phase={last_observed.get('phase_label')!r}"
        )
    raise RuntimeError(f"timed out waiting for job: {label}.{detail}")


def _wait_for_job_id(
    api_base: str,
    job_id: str,
    *,
    expected_statuses: set[str],
    timeout_s: int = WAIT_TIMEOUT_S,
    label: str,
) -> dict:
    terminal_statuses = {"cancelled", "failed", "succeeded"}
    deadline = time.time() + timeout_s
    last_observed: dict | None = None
    while time.time() < deadline:
        try:
            payload = _http_json(f"{api_base}/api/jobs/{job_id}")
        except (URLError, OSError, AssertionError):
            time.sleep(POLL_INTERVAL_S)
            continue
        assert isinstance(payload, dict)
        last_observed = payload
        status = str(payload.get("status") or "").strip()
        if status in expected_statuses:
            return payload
        if status in terminal_statuses:
            summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
            detail = (
                f" id={payload.get('id')!r}"
                f" status={payload.get('status')!r}"
                f" phase={payload.get('phase_label')!r}"
                f" latest_error={payload.get('latest_error')!r}"
            )
            if summary:
                detail += f" summary_error_code={summary.get('error_code')!r} summary_with_error={summary.get('with_error')!r}"
            raise RuntimeError(f"job reached unexpected terminal status while waiting for {label}.{detail}")
        time.sleep(POLL_INTERVAL_S)
    detail = ""
    if isinstance(last_observed, dict):
        last_summary = last_observed.get("summary") if isinstance(last_observed.get("summary"), dict) else {}
        detail = (
            f" last_observed_id={last_observed.get('id')!r}"
            f" status={last_observed.get('status')!r}"
            f" phase={last_observed.get('phase_label')!r}"
            f" latest_error={last_observed.get('latest_error')!r}"
        )
        if last_summary:
            detail += f" summary_error_code={last_summary.get('error_code')!r} summary_with_error={last_summary.get('with_error')!r}"
    raise RuntimeError(f"timed out waiting for job: {label}.{detail}")


def _wait_until(locator, *, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if locator.is_visible():
            return
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"locator not visible within {timeout_s}s")


def _ensure_checkbox_selected(locator, *, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            checked = str(locator.get_attribute("aria-checked") or "").lower()
            if checked == "true":
                return
            if locator.is_visible() and locator.is_enabled():
                locator.click(force=True)
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"checkbox did not become selected within {timeout_s}s")


def _wait_for_any_visible(locators: list, *, timeout_s: int = 60, label: str) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for locator in locators:
            try:
                if locator.is_visible():
                    return
            except Exception:
                pass
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"{label} not visible within {timeout_s}s")


def _goto_with_retry(page, url: str, *, wait_until: str = "domcontentloaded", timeout_ms: int = 30_000, attempts: int = 5) -> None:
    last_error: Exception | None = None
    for _ in range(attempts):
        for candidate in _loopback_url_variants(url):
            try:
                page.goto(candidate, wait_until=wait_until, timeout=timeout_ms)
                return
            except Exception as exc:
                last_error = exc
        time.sleep(POLL_INTERVAL_S)
    assert last_error is not None
    raise last_error


def _launch_e2e_browser(playwright):
    try:
        return playwright.webkit.launch(headless=True)
    except Exception:
        try:
            return playwright.chromium.launch(headless=True, args=["--no-proxy-server"])
        except Exception as exc:
            global _PLAYWRIGHT_BROWSER_READY
            if _PLAYWRIGHT_BROWSER_READY or "Executable doesn't exist" not in str(exc):
                raise
            _heartbeat("install playwright chromium for non-live e2e")
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            _PLAYWRIGHT_BROWSER_READY = True
            return playwright.chromium.launch(headless=True, args=["--no-proxy-server"])


def _label_pattern(*labels: str) -> re.Pattern[str]:
    escaped = [re.escape(label) for label in labels]
    return re.compile(rf"^(?:{'|'.join(escaped)})$")


def _new_non_live_context(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
    context.add_init_script(
        """
        (() => {
          window.localStorage.setItem('movi.locale', 'en');
          document.documentElement.lang = 'en';
        })();
        """
    )
    return context


def _wait_for_dashboard_ready(page, *, timeout_s: int = WAIT_TIMEOUT_S) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        probe_timeout = min(20, max(5, int(deadline - time.time())))
        sidebar = page.locator("aside")
        try:
            _wait_for_any_visible(
                [
                    sidebar.get_by_role("link", name=_label_pattern("Analyze", "分析")),
                    page.get_by_role("button", name=_label_pattern("Job Center", "作业中心")),
                ],
                timeout_s=probe_timeout,
                label="app-shell anchors",
            )
            _wait_for_any_visible(
                [
                    page.get_by_role("link", name=_label_pattern("Start Analyze", "开始 Analyze")),
                    page.get_by_role("link", name=_label_pattern("4-step guided flow", "4 步引导流程")),
                    page.get_by_role("link", name=_label_pattern("Jobs History", "查看作业历史")),
                ],
                timeout_s=probe_timeout,
                label="dashboard anchors",
            )
            return
        except Exception as exc:
            last_error = exc
            current_url = page.url
            home_url: str | None = None
            match = re.match(r"^(https?://[^/]+)/app(?:/.*)?$", current_url)
            if match:
                home_url = f"{match.group(1)}/app/"
            if home_url and current_url.rstrip("/") != home_url.rstrip("/"):
                try:
                    _goto_with_retry(page, home_url, timeout_ms=15_000, attempts=2)
                except Exception:
                    pass
            elif home_url is None:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=15_000)
                except Exception:
                    pass
            else:
                try:
                    page.wait_for_load_state("networkidle", timeout=5_000)
                except Exception:
                    pass
            time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"dashboard not ready within {timeout_s}s: url={page.url} last_error={last_error}")


def _wait_for_analyze_ready(page, *, timeout_s: int = WAIT_TIMEOUT_S) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        probe_timeout = min(20, max(5, int(deadline - time.time())))
        try:
            _wait_for_any_visible(
                [
                    page.get_by_role("heading", name=_label_pattern("Analyze Wizard", "Analyze 向导")),
                    page.get_by_role("heading", name=_label_pattern("Step 1 - Choose Input Source", "第 1 步 - 选择输入来源")),
                    page.locator("#dir-path"),
                ],
                timeout_s=probe_timeout,
                label="analyze anchors",
            )
            return
        except Exception as exc:
            last_error = exc
            current_url = page.url
            if re.search(r"/analyze(?:[/?#].*)?$", current_url):
                try:
                    _goto_with_retry(page, current_url, timeout_ms=15_000, attempts=2)
                except Exception:
                    pass
            else:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=15_000)
                except Exception:
                    pass
            time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"analyze page not ready within {timeout_s}s: url={page.url} last_error={last_error}")


def _wait_for_sidebar_nav_contract(page, *, timeout_s: int = WAIT_TIMEOUT_S) -> None:
    nav = page.locator("aside")
    for labels in (
        ("Dashboard", "仪表盘"),
        ("Jobs", "作业"),
        ("Analyze", "分析"),
        ("Manifest", "Manifest"),
        ("Conflicts", "冲突"),
        ("Apply", "Apply"),
        ("Report", "Report"),
        ("Rollback", "Rollback"),
    ):
        _wait_until(nav.get_by_role("link", name=_label_pattern(*labels)), timeout_s=timeout_s)


def _wait_for_input_value(locator, expected: str, *, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if locator.input_value() == expected:
                return
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"input value did not become {expected!r} within {timeout_s}s")


def _wait_for_input_value_not(locator, unexpected: str, *, timeout_s: int = 60) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            current = locator.input_value()
            if current != unexpected:
                return current
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"input value did not change from {unexpected!r} within {timeout_s}s")


def _wait_for_locator_count(locator, expected: int, *, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if locator.count() == expected:
                return
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"locator count did not become {expected} within {timeout_s}s")


def _wait_for_manifest_row(page, preferred_text: str, *, timeout_s: int = WAIT_TIMEOUT_S):
    deadline = time.time() + timeout_s
    preferred_row = page.get_by_role("row").filter(has_text=preferred_text).first
    while time.time() < deadline:
        try:
            if preferred_row.is_visible():
                return preferred_row
        except Exception:
            pass

        rows = page.get_by_role("row")
        try:
            count = rows.count()
            for idx in range(1, count):
                row = rows.nth(idx)
                if row.is_visible():
                    return row
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"manifest row not visible within {timeout_s}s (preferred_text={preferred_text!r})")


def _select_option_with_retry(locator, value: str, *, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            locator.select_option(value=value)
            if locator.input_value() == value:
                return
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"select option {value!r} not available within {timeout_s}s")


def _wait_for_enabled_state(locator, *, enabled: bool, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if locator.is_enabled() is enabled:
                return
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"locator enabled state did not become {enabled} within {timeout_s}s")


def _wait_for_rollback_dry_run_badge(page, *, timeout_s: int = WAIT_TIMEOUT_S) -> None:
    """Wait until rollback dry-run approval is reflected in UI.

    The rollback page updates dry-run state via live job polling. Under heavy test load,
    polling can lag; clicking the log panel refresh button triggers a direct refresh.
    """
    approved_badge = page.get_by_text(re.compile(r"^(?:Dry[- ]Run 已通过|Dry-Run Approved|Preview Approved)$"))
    refresh_button = page.get_by_role("button", name=re.compile(r"^(?:刷新|Refresh)$"))
    deadline = time.time() + timeout_s
    next_refresh_at = time.time()
    while time.time() < deadline:
        try:
            if approved_badge.is_visible():
                return
        except Exception:
            pass
        now = time.time()
        if now >= next_refresh_at:
            try:
                _click_first_visible_enabled(refresh_button, timeout_s=2, label="rollback log refresh")
            except Exception:
                pass
            next_refresh_at = now + 1.0
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError("rollback dry-run approval badge did not appear in UI")


def _click_first_visible_enabled(locator, *, timeout_s: int = 60, label: str) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            count = locator.count()
            for index in range(count):
                candidate = locator.nth(index)
                if candidate.is_visible() and candidate.is_enabled():
                    candidate.click(timeout=1_000, force=True)
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(POLL_INTERVAL_S)
    if last_error is not None:
        raise RuntimeError(f"failed to click enabled locator for {label}: {last_error}") from last_error
    raise RuntimeError(f"failed to click enabled locator for {label} within {timeout_s}s")


def _wait_for_path_state(path: Path, *, exists: bool, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.exists() is exists:
            return
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"path state did not become exists={exists}: {path}")


def _wait_for_conflicts_page_ready(page, *, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        anchors = (
            page.get_by_role("heading", name=re.compile(r"^Conflicts?$|^Conflict Center$")),
            page.get_by_text(re.compile(r"^(?:冲突总数|Total Conflicts)$")),
            page.get_by_role("button", name=re.compile(r"^(?:刷新冲突|Refresh Conflicts)$")),
            page.locator("input[placeholder='搜索冲突原因或路径'], input[placeholder='Search conflict reason or path']").first,
        )
        for locator in anchors:
            try:
                if locator.is_visible():
                    return
            except Exception:
                continue
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"conflicts page not ready within {timeout_s}s")


def _wait_for_jobs_ready(page, *, timeout_s: int = WAIT_TIMEOUT_S) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        probe_timeout = min(20, max(5, int(deadline - time.time())))
        try:
            _wait_for_any_visible(
                [
                    page.get_by_role("heading", name=_label_pattern("Jobs Runtime", "作业与历史")),
                    page.locator(
                        "input[placeholder='搜索 job id / phase / status'], input[placeholder='Search job id / phase / status']"
                    ).first,
                    page.get_by_role("heading", name=_label_pattern("Current Job", "当前作业")),
                    page.locator("aside").get_by_role("link", name=_label_pattern("Analyze", "分析")),
                ],
                timeout_s=probe_timeout,
                label="jobs page anchors",
            )
            return
        except Exception as exc:
            last_error = exc
            current_url = page.url
            target_url = current_url if "/app/jobs" in current_url else None
            if target_url is None:
                host_match = re.match(r"^(https?://[^/]+)/app(?:/.*)?$", current_url)
                if host_match:
                    target_url = f"{host_match.group(1)}/app/jobs"
            if target_url:
                try:
                    _goto_with_retry(page, target_url, timeout_ms=15_000, attempts=2)
                except Exception:
                    pass
            else:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=15_000)
                except Exception:
                    pass
            time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"jobs page not ready within {timeout_s}s: url={page.url} last_error={last_error}")


def _wait_for_manifest_ready(page, *, timeout_s: int = WAIT_TIMEOUT_S) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        probe_timeout = min(20, max(5, int(deadline - time.time())))
        try:
            _wait_for_any_visible(
                [
                    page.get_by_role("heading", name=re.compile(r"^(?:Manifest 编辑工作台|Manifest Workbench)$")),
                    page.locator(
                        "input[placeholder='搜索文件名/分类/错误码/目标建议'], "
                        "input[placeholder='Search filename / category / error code / suggested target']"
                    ).first,
                    page.get_by_placeholder(re.compile(r"^(?:批量设置分类|Set category for selected rows)$")),
                    page.get_by_role("button", name=re.compile(r"^(?:保存修改|Save Edits)")),
                    page.locator("aside").get_by_role("link", name=_label_pattern("Analyze", "分析")),
                ],
                timeout_s=probe_timeout,
                label="manifest page anchors",
            )
            return
        except Exception as exc:
            last_error = exc
            current_url = page.url
            target_url = current_url if "/app/manifest/" in current_url else None
            if target_url is None:
                host_match = re.match(r"^(https?://[^/]+)/app(?:/.*)?$", current_url)
                if host_match:
                    target_url = f"{host_match.group(1)}/app/"
            if target_url:
                try:
                    _goto_with_retry(page, target_url, timeout_ms=15_000, attempts=2)
                except Exception:
                    pass
            else:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=15_000)
                except Exception:
                    pass
            time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"manifest page not ready within {timeout_s}s: url={page.url} last_error={last_error}")


def _terminate_subprocess_safely(proc: subprocess.Popen[str], *, label: str, timeout_s: int = 10) -> None:
    """Terminate only the intended child process; never touch pytest parent/itself."""
    pid = int(proc.pid)
    current_pid = os.getpid()
    parent_pid = os.getppid()
    if pid in {current_pid, parent_pid}:
        raise RuntimeError(f"refuse to terminate {label}: target pid={pid} is current/parent process")
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout_s)


def _open_job_center(page, *, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            trigger = page.locator("button:has-text('Job Center'):visible, button:has-text('作业中心'):visible").first
            if trigger.is_visible():
                trigger.click(timeout=5_000)
            else:
                page.get_by_role("button", name=_label_pattern("Job Center", "作业中心")).click(timeout=5_000)
        except Exception as exc:
            last_error = exc
            time.sleep(POLL_INTERVAL_S)
            continue

        for ready_locator in (
            page.get_by_placeholder("搜索 job id / kind / status"),
            page.get_by_role("heading", name=_label_pattern("Job Center", "作业中心")),
        ):
            try:
                if ready_locator.is_visible():
                    return
            except Exception:
                continue
        time.sleep(POLL_INTERVAL_S)

    if last_error is not None:
        raise RuntimeError(f"failed to open Job Center within {timeout_s}s: {last_error}") from last_error
    raise RuntimeError(f"failed to open Job Center within {timeout_s}s")


def _close_job_center(page, *, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            close_locator = page.locator("[role='dialog']:has-text('Job Center'), [role='dialog']:has-text('作业中心')").get_by_role(
                "button", name=re.compile(r"^(?:Close|关闭)$")
            )
            _click_first_visible_enabled(close_locator, timeout_s=2, label="job center close")
        except Exception as exc:
            last_error = exc
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
        try:
            if not page.get_by_role("heading", name=_label_pattern("Job Center", "作业中心")).is_visible():
                return
        except Exception:
            return
        time.sleep(POLL_INTERVAL_S)
    if last_error is not None:
        raise RuntimeError(f"failed to close Job Center within {timeout_s}s: {last_error}") from last_error
    raise RuntimeError(f"failed to close Job Center within {timeout_s}s")


def _ensure_webui_dist(repo_root: Path, run_env: dict[str, str], log_dir: Path, *, reason: str) -> None:
    global _WEBUI_DIST_READY

    dist_index = repo_root / ".runtime-cache" / "build" / "apps" / "webui" / "index.html"
    if _WEBUI_DIST_READY and dist_index.exists():
        return

    def _run_build() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["npm", "--prefix", "apps/webui", "run", "build"],
            cwd=repo_root,
            env=run_env,
            stdout=build_log_file,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )

    def _reinstall_webui_dependencies() -> None:
        node_modules = repo_root / "apps" / "webui" / "node_modules"
        shutil.rmtree(node_modules, ignore_errors=True)
        install_cmd = (
            ["npm", "--prefix", "apps/webui", "ci"]
            if (repo_root / "apps" / "webui" / "package-lock.json").exists()
            else ["npm", "--prefix", "apps/webui", "install"]
        )
        subprocess.run(
            install_cmd,
            cwd=repo_root,
            env=run_env,
            stdout=build_log_file,
            stderr=subprocess.STDOUT,
            check=True,
            text=True,
        )

    build_log = log_dir / "webui-build.log"
    _heartbeat(f"build webui dist for static-host {reason}")
    with build_log.open("w", encoding="utf-8") as build_log_file:
        if not _webui_dependencies_ready(repo_root, run_env):
            _heartbeat("install webui dependencies for static-host e2e")
            _reinstall_webui_dependencies()

        max_attempts = 3
        build_proc: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            args=["npm", "--prefix", "apps/webui", "run", "build"], returncode=1
        )
        for attempt in range(1, max_attempts + 1):
            build_proc = _run_build()
            build_log_file.flush()
            log_tail = build_log.read_text(encoding="utf-8", errors="ignore")[-3000:]
            if build_proc.returncode == 0 and dist_index.exists():
                break

            if _build_log_indicates_missing_webui_tooling(log_tail):
                _heartbeat("install webui dependencies for static-host e2e")
                _reinstall_webui_dependencies()
                continue

            if "npm has a bug related to optional dependencies" in log_tail or "Cannot find module @rollup/rollup-" in log_tail:
                _heartbeat("reinstall webui dependencies for platform-specific native packages")
                _reinstall_webui_dependencies()
                continue

            transient_codes = {130, 137, 143}
            transient_signals = ("Terminated", "Killed")
            if attempt < max_attempts and (
                build_proc.returncode in transient_codes or any(signal in log_tail for signal in transient_signals)
            ):
                _heartbeat(
                    "retry webui dist build after transient interruption "
                    f"(attempt {attempt}/{max_attempts}, return_code={build_proc.returncode})"
                )
                time.sleep(1.0)
                continue
            break

        if build_proc.returncode != 0 or not dist_index.exists():
            log_tail = build_log.read_text(encoding="utf-8", errors="ignore")[-3000:] if build_log.exists() else ""
            raise RuntimeError(
                f"non-live webui e2e failed to prepare static dist (reason={reason}, return_code={build_proc.returncode}): {log_tail}"
            )

    _WEBUI_DIST_READY = True


def _write_slow_api_module(path: Path) -> Path:
    module_path = path / "slow_web_api_app.py"
    module_path.write_text(
        """
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Sequence

from apps.api import web_api


def slow_executor(
    command: Sequence[str],
    cwd: Path,
    emit: Callable[[str, str, dict[str, Any]], None],
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    emit("info", "slow_executor_start", {"command": " ".join(command)})
    for step in range(240):
        if should_cancel and should_cancel():
            raise web_api.JobCancelled("cancel requested in slow executor")
        emit("info", "slow_executor_tick", {"step": step})
        time.sleep(0.1)
    if should_cancel and should_cancel():
        raise web_api.JobCancelled("cancel requested in slow executor")


app = web_api.create_app(command_executor=slow_executor)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return module_path


@pytest.fixture
def e2e_cleanup_actions():
    actions: list[tuple[str, Callable[[], None]]] = []
    yield actions
    failures: list[str] = []
    for label, callback in reversed(actions):
        try:
            callback()
        except Exception as exc:  # pragma: no cover - cleanup is environment dependent
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
    if failures:
        pytest.fail("webui_e2e teardown failed: " + "; ".join(failures))


def test_webui_playwright_non_live_env_preflight():
    if shutil.which("npm") is None:
        pytest.fail("webui non-live e2e requires npm in PATH")
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.fail(f"webui non-live e2e requires playwright: {exc}")


def test_build_log_indicates_missing_webui_tooling_matches_shell_variants():
    assert _build_log_indicates_missing_webui_tooling("sh: 1: tsc: not found")
    assert _build_log_indicates_missing_webui_tooling("vite: command not found")
    assert _build_log_indicates_missing_webui_tooling("TS2307: Cannot find module '@tanstack/react-table'")
    assert _build_log_indicates_missing_webui_tooling("TS7016: Could not find a declaration file for module 'react/jsx-runtime'")
    assert not _build_log_indicates_missing_webui_tooling("Error: ENOENT: no such file or directory")


def test_webui_playwright_non_live_full_journey(e2e_cleanup_actions, tmp_path: Path):
    if shutil.which("npm") is None:
        pytest.fail("webui non-live e2e requires npm in PATH")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.fail(f"webui non-live e2e requires playwright: {exc}")

    repo_root = _repo_root()
    python_bin = repo_root / ".runtime-cache" / "venv" / "default" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path(sys.executable)

    run_env = dict(os.environ)
    run_env["PYTHONUNBUFFERED"] = run_env.get("PYTHONUNBUFFERED") or "1"
    run_env["MOVI_ALLOW_HOST_EXECUTION"] = run_env.get("MOVI_ALLOW_HOST_EXECUTION") or "1"
    run_env["MOVI_IN_CONTAINER"] = run_env.get("MOVI_IN_CONTAINER") or "0"
    run_env["MOVI_ROLLBACK_HMAC_KEY"] = run_env.get("MOVI_ROLLBACK_HMAC_KEY") or "webui-playwright-e2e-key"
    run_env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{run_env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    run_env["MOVI_RUN_LIVE_TESTS"] = "0"
    run_env["MOVI_RUN_WEBUI_E2E"] = "0"
    workspace_root = tmp_path / "workspace"
    run_env["MOVI_WORKSPACE_ROOT"] = str(workspace_root)
    run_env["MOVI_INPUT_ROOT"] = str(workspace_root / "data" / "raw")
    run_env["MOVI_OUTPUT_ROOT"] = str(workspace_root / "data" / "organized")

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    api_log = log_dir / "web_api.log"

    api_port = _find_free_port()
    api_base = f"http://127.0.0.1:{api_port}"
    browser_ui_base = f"http://127.0.0.1:{api_port}/app"

    _ensure_webui_dist(repo_root, run_env, log_dir, reason="non-live e2e")

    with api_log.open("w", encoding="utf-8") as api_log_file:
        _heartbeat("start isolated web api server")
        api_proc = subprocess.Popen(
            [
                str(python_bin),
                "-m",
                "apps.api.server",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            cwd=repo_root,
            env=run_env,
            stdout=api_log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        e2e_cleanup_actions.append(("terminate_web_api", lambda proc=api_proc: _terminate_subprocess_safely(proc, label="web_api")))

        _heartbeat("wait web api ready")
        _wait_http_ready(f"{api_base}/openapi.json", timeout_s=READY_TIMEOUT_S, name="web api")
        _wait_http_ready(browser_ui_base, timeout_s=READY_TIMEOUT_S, name="static web ui")

        token = uuid.uuid4().hex[:8]
        source_name = f"e2e-nonlive-{token}.png"
        source_dir = Path(run_env["MOVI_INPUT_ROOT"]).expanduser() / f"e2e-nonlive-{token}"
        source_dir.mkdir(parents=True, exist_ok=True)
        source_path = source_dir / source_name
        source_path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0bIDAT\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xf4\x8f\xb6"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        e2e_cleanup_actions.append(("cleanup_source_dir", lambda: shutil.rmtree(source_dir, ignore_errors=True)))

        with sync_playwright() as p:
            browser = _launch_e2e_browser(p)
            context = _new_non_live_context(browser)
            page = context.new_page()

            _heartbeat("dashboard")
            _goto_with_retry(page, f"{browser_ui_base}/")
            _wait_for_dashboard_ready(page)

            _heartbeat("sidebar nav contract")
            _wait_for_sidebar_nav_contract(page)
            page.locator("aside").get_by_role("link", name=_label_pattern("Jobs", "作业")).click()
            page.wait_for_url("**/jobs", timeout=30_000)
            _wait_for_jobs_ready(page, timeout_s=WAIT_TIMEOUT_S)
            page.locator("aside").get_by_role("link", name=_label_pattern("Analyze", "分析")).click()
            page.wait_for_url("**/analyze", timeout=30_000)
            _wait_for_analyze_ready(page)
            _goto_with_retry(page, f"{browser_ui_base}/")
            _wait_for_dashboard_ready(page)

            _heartbeat("dashboard cta routing")
            page.get_by_role("link", name=_label_pattern("4-step guided flow", "4 步引导流程")).click()
            page.wait_for_url("**/analyze", timeout=30_000)
            _wait_for_analyze_ready(page)

            _goto_with_retry(page, f"{browser_ui_base}/")
            _wait_for_dashboard_ready(page)
            page.get_by_role("link", name=_label_pattern("Jobs History", "查看作业历史")).click()
            page.wait_for_url("**/jobs", timeout=30_000)
            _wait_for_jobs_ready(page, timeout_s=WAIT_TIMEOUT_S)
            _wait_until(page.get_by_role("banner").get_by_text(re.compile("SSE")))
            _goto_with_retry(page, f"{browser_ui_base}/")
            _wait_for_dashboard_ready(page)

            _heartbeat("not found route")
            _goto_with_retry(page, f"{browser_ui_base}/unknown-{token}")
            _wait_until(page.get_by_role("heading", name=re.compile(r"^(?:Page not found|页面未找到)$")))
            _wait_until(page.get_by_role("link", name=re.compile(r"^(?:Back to home|返回首页)$")))
            page.get_by_role("link", name=re.compile(r"^(?:Back to home|返回首页)$")).click()
            page.wait_for_url(re.compile(r".*/app/?$"), timeout=30_000)
            _wait_for_dashboard_ready(page)

            _heartbeat("analyze")
            page.get_by_role("link", name=_label_pattern("Analyze", "分析")).click()
            page.wait_for_url("**/analyze", timeout=30_000)
            _wait_for_analyze_ready(page)

            page.locator("#dir-path").fill(str(source_dir))
            page.get_by_role("button", name="Next").click()

            step2_switches = page.get_by_role("switch")
            if step2_switches.count() > 0:
                step2_switches.nth(0).click(force=True)
            else:
                step2_checkboxes = page.get_by_role("checkbox")
                if step2_checkboxes.count() > 0:
                    step2_checkboxes.first.check(force=True)
            page.get_by_role("button", name="Next").click()

            with page.expect_response(
                lambda response: response.request.method == "POST" and response.url.endswith("/api/jobs/analyze"),
                timeout=30_000,
            ) as analyze_response_info:
                page.get_by_role("button", name="Run Analyze").click()
            analyze_response = analyze_response_info.value
            assert analyze_response.status == 202
            analyze_payload = analyze_response.json()
            analyze_job_id = str(analyze_payload.get("id") or "")
            assert analyze_job_id.startswith("job_")

            _wait_for_job_id(api_base, analyze_job_id, expected_statuses={"succeeded"}, label="analyze succeeded")

            _heartbeat("manifest")
            analyze_job = _http_json(f"{api_base}/api/jobs/{analyze_job_id}")
            assert isinstance(analyze_job, dict)
            analyze_manifest_path = str(((analyze_job.get("summary") or {}).get("manifest_path") or "")).strip()
            assert analyze_manifest_path

            _heartbeat("dashboard apply cta")
            _goto_with_retry(page, f"{browser_ui_base}/")
            _wait_for_dashboard_ready(page)
            _wait_until(page.get_by_role("link", name=_label_pattern("Apply Dry-Run", "执行 Apply Dry-Run")), timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("link", name=_label_pattern("Apply Dry-Run", "执行 Apply Dry-Run")).click()
            page.wait_for_url("**/apply/*", timeout=30_000)
            _wait_until(page.get_by_role("heading", name=_label_pattern("Apply Confirmation", "执行确认")))
            page.get_by_role("link", name=_label_pattern("Back to Review Queue", "返回 Review Queue")).click()
            page.wait_for_url("**/review/*", timeout=30_000)

            _heartbeat("review queue")
            _wait_until(page.get_by_role("heading", name=re.compile(r"^Movi Review$")), timeout_s=WAIT_TIMEOUT_S)
            _wait_until(page.get_by_text(source_name).first, timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("link", name="Open Manifest Workbench").click()
            page.wait_for_url("**/manifest/*", timeout=30_000)
            _heartbeat("manifest")
            _wait_for_manifest_ready(page, timeout_s=WAIT_TIMEOUT_S)
            manifest_row = _wait_for_manifest_row(page, source_name, timeout_s=WAIT_TIMEOUT_S)
            manifest_row.locator("input[type='checkbox']").first.check(force=True)
            _wait_until(page.get_by_text(re.compile(r"^(?:选中 1|Selected 1)$")), timeout_s=WAIT_TIMEOUT_S)

            page.get_by_placeholder("Set category for selected rows").fill("自动化回归")
            page.get_by_role("button", name="Apply", exact=True).click()
            with page.expect_response(
                lambda response: response.request.method == "POST" and response.url.endswith(f"/api/jobs/{analyze_job_id}/manifest/batch"),
                timeout=30_000,
            ) as save_category_response_info:
                page.get_by_role("button", name=re.compile(r"^(?:保存修改|Save Edits)")).click()
            save_category_response = save_category_response_info.value
            assert save_category_response.status == 200

            manifest_rows_payload = _http_json(f"{api_base}/api/jobs/{analyze_job_id}/manifest/view")
            assert isinstance(manifest_rows_payload, dict)
            manifest_rows = manifest_rows_payload.get("rows") if isinstance(manifest_rows_payload.get("rows"), list) else []
            assert manifest_rows, "manifest rows should not be empty after analyze"
            source_row: dict | None = None
            source_row_index = 0
            for index, row in enumerate(manifest_rows):
                if isinstance(row, dict) and (str(row.get("file_name") or "") == source_name or source_name in str(row.get("path") or "")):
                    source_row = row
                    source_row_index = index
                    break
            if not isinstance(source_row, dict):
                for index, row in enumerate(manifest_rows):
                    if isinstance(row, dict):
                        source_row = row
                        source_row_index = index
                        break
            assert isinstance(source_row, dict), f"manifest should contain source row: {source_name}"
            first_row_id = str(source_row.get("row_id") or source_row_index)

            template_name = f"模板-{token}"
            template_pattern = "tmpl__{hash8}"
            page.get_by_placeholder(re.compile(r"^(?:模板名|Template name)$")).fill(template_name)
            page.get_by_placeholder("{category}/{title}__{hash8}").fill(template_pattern)
            with page.expect_response(
                lambda response: response.request.method == "POST" and response.url.endswith("/api/preferences/naming-templates"),
                timeout=30_000,
            ) as create_template_response_info:
                page.get_by_role("button", name=re.compile(r"^(?:新建模板|Create Template)$")).click()
            create_template_response = create_template_response_info.value
            assert create_template_response.status == 200
            create_template_payload = create_template_response.json()
            template_id = str(create_template_payload.get("key") or "").strip()
            assert template_id, "created template id should not be empty"
            templates_payload = _http_json(f"{api_base}/api/preferences/naming-templates")
            assert isinstance(templates_payload, dict)
            raw_template_items = templates_payload.get("items")
            template_items: list[object] = raw_template_items if isinstance(raw_template_items, list) else []
            assert any(isinstance(item, dict) and str(item.get("key") or "") == template_id for item in template_items)

            template_trigger = page.get_by_role(
                "button",
                name=re.compile(r"^(?:套模板|Apply Template)$"),
            ).locator("xpath=preceding::button[@role='combobox'][1]")
            _wait_until(template_trigger, timeout_s=WAIT_TIMEOUT_S)
            template_trigger.click()
            template_option = page.get_by_role("option", name=template_name).first
            _wait_until(template_option, timeout_s=WAIT_TIMEOUT_S)
            template_option.click()
            manifest_row.locator("input[type='checkbox']").first.check(force=True)
            _wait_until(page.get_by_text(re.compile(r"^(?:选中 1|Selected 1)$")), timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("button", name=re.compile(r"^(?:套模板|Apply Template)$")).click()
            _wait_until(page.get_by_role("button", name=re.compile(r"^(?:保存修改|Save Edits) \([1-9]\d*\)$")), timeout_s=WAIT_TIMEOUT_S)

            expected_template_target = f"tmpl__{first_row_id[-8:]}"
            with page.expect_response(
                lambda response: response.request.method == "POST" and response.url.endswith(f"/api/jobs/{analyze_job_id}/manifest/batch"),
                timeout=30_000,
            ) as save_template_response_info:
                page.get_by_role("button", name=re.compile(r"^(?:保存修改|Save Edits)")).click()
            save_template_response = save_template_response_info.value
            assert save_template_response.status == 200

            template_rows_payload = _http_json(f"{api_base}/api/jobs/{analyze_job_id}/manifest/view")
            assert isinstance(template_rows_payload, dict)
            raw_template_rows = template_rows_payload.get("rows")
            template_rows: list[object] = raw_template_rows if isinstance(raw_template_rows, list) else []
            persisted_row = next(
                (
                    row
                    for row in template_rows
                    if isinstance(row, dict) and (str(row.get("row_id") or "") == first_row_id or source_name in str(row.get("path") or ""))
                ),
                None,
            )
            if not isinstance(persisted_row, dict):
                candidate_row = template_rows[source_row_index] if source_row_index < len(template_rows) else None
                persisted_row = candidate_row if isinstance(candidate_row, dict) else None
            if not isinstance(persisted_row, dict):
                persisted_row = template_rows[0] if template_rows and isinstance(template_rows[0], dict) else None
            assert isinstance(persisted_row, dict), "persisted source row should exist after applying template"
            assert str(persisted_row.get("new_path") or "") == expected_template_target

            _goto_with_retry(page, f"{browser_ui_base}/manifest/{analyze_job_id}")
            _wait_for_manifest_ready(page, timeout_s=WAIT_TIMEOUT_S)
            _wait_until(page.locator(f"input[value='{expected_template_target}']").first, timeout_s=WAIT_TIMEOUT_S)

            execute_target = str((Path(run_env["MOVI_OUTPUT_ROOT"]).expanduser() / f"e2e-nonlive-{token}-renamed.png").resolve())
            _http_json_request(
                f"{api_base}/api/jobs/{analyze_job_id}/manifest/batch",
                method="POST",
                payload={
                    "operations": [
                        {"row_id": first_row_id, "patch": {"new_path": execute_target}},
                    ]
                },
            )

            view_name = f"视图-{token}"
            page.get_by_placeholder(re.compile(r"^(?:视图名称|View name)$")).fill(view_name)
            page.get_by_role("button", name=re.compile(r"^(?:保存视图|Save View)$")).click()
            _wait_until(page.get_by_role("button", name=view_name))
            views_payload = _http_json(f"{api_base}/api/preferences/views")
            assert isinstance(views_payload, dict)
            raw_saved_view_items = views_payload.get("items")
            saved_view_items: list[object] = raw_saved_view_items if isinstance(raw_saved_view_items, list) else []
            assert any(
                isinstance(item, dict) and isinstance(item.get("value"), dict) and str(item["value"].get("name") or "") == view_name
                for item in saved_view_items
            )

            manifest_search_input = page.locator(
                "input[placeholder='搜索文件名/分类/错误码/目标建议'], "
                "input[placeholder='Search filename / category / error code / suggested target']"
            ).first
            manifest_search_input.fill("临时筛选条件")
            _wait_for_input_value(manifest_search_input, "临时筛选条件", timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("button", name=view_name).click()
            _wait_for_input_value(manifest_search_input, "", timeout_s=WAIT_TIMEOUT_S)
            delete_saved_view_button = page.get_by_role("button", name=view_name).locator("xpath=following-sibling::button[1]")
            delete_saved_view_button.click()
            _wait_for_locator_count(page.get_by_role("button", name=view_name), 0, timeout_s=WAIT_TIMEOUT_S)
            views_after_delete = _http_json(f"{api_base}/api/preferences/views")
            assert isinstance(views_after_delete, dict)
            raw_saved_view_items_after_delete = views_after_delete.get("items")
            saved_view_items_after_delete: list[object] = (
                raw_saved_view_items_after_delete if isinstance(raw_saved_view_items_after_delete, list) else []
            )
            assert not any(
                isinstance(item, dict) and isinstance(item.get("value"), dict) and str(item["value"].get("name") or "") == view_name
                for item in saved_view_items_after_delete
            )

            manifest_row.locator("input[type='checkbox']").first.check(force=True)
            _wait_until(page.get_by_text(re.compile(r"^(?:选中 1|Selected 1)$")), timeout_s=WAIT_TIMEOUT_S)
            manifest_selected_scope = page.locator("main").filter(has=page.get_by_text(re.compile(r"^(?:选中 1|Selected 1)$"))).first
            ignore_buttons = manifest_selected_scope.locator("button:has-text('批量忽略'), button:has-text('Ignore Selected')")
            if ignore_buttons.count() == 0:
                ignore_buttons = page.locator("button:has-text('批量忽略'), button:has-text('Ignore Selected')")
            _click_first_visible_enabled(ignore_buttons, timeout_s=30, label="manifest bulk ignore")
            _wait_until(page.get_by_role("button", name=re.compile(r"^(?:保存修改|Save Edits) \([1-9]\d*\)$")), timeout_s=WAIT_TIMEOUT_S)
            unignore_buttons = manifest_selected_scope.locator("button:has-text('取消忽略'), button:has-text('Unignore Selected')")
            if unignore_buttons.count() == 0:
                unignore_buttons = page.locator("button:has-text('取消忽略'), button:has-text('Unignore Selected')")
            _click_first_visible_enabled(unignore_buttons, timeout_s=30, label="manifest bulk unignore")
            _wait_until(page.get_by_role("button", name=re.compile(r"^(?:保存修改|Save Edits) \(0\)$")), timeout_s=WAIT_TIMEOUT_S)
            _http_json_request(
                f"{api_base}/api/jobs/{analyze_job_id}/manifest/batch",
                method="POST",
                payload={
                    "operations": [
                        {"row_id": first_row_id, "patch": {"new_path": execute_target}},
                    ]
                },
            )

            _heartbeat("apply")
            page.get_by_role("link", name=re.compile(r"^(?:进入 Apply Dry-Run|Open Apply Dry-Run)$")).click()
            page.wait_for_url("**/apply/*", timeout=30_000)
            _wait_until(page.get_by_role("heading", name=_label_pattern("Apply Confirmation", "执行确认")))
            preview_changes_button = page.get_by_role("button", name=re.compile(r"^(?:运行 Dry-Run|Run Dry-Run|Preview Changes)$"))
            _wait_until(preview_changes_button, timeout_s=WAIT_TIMEOUT_S)
            preview_changes_button.click()

            dry_run_apply = _wait_for_job(
                api_base,
                lambda item: (
                    item.get("kind") == "apply"
                    and item.get("status") == "succeeded"
                    and bool((item.get("summary") or {}).get("dry_run"))
                    and str(((item.get("summary") or {}).get("source_manifest_path") or "")).strip() == analyze_manifest_path
                ),
                label="apply dry-run succeeded",
            )
            assert str(dry_run_apply.get("id") or "").startswith("job_")
            dry_run_apply_id = str(dry_run_apply.get("id") or "")

            first_real_apply_button = page.get_by_role("button", name=re.compile(r"^(?:执行真实 Apply|Run Apply|Organize Now)$"))
            _wait_for_enabled_state(first_real_apply_button, enabled=True, timeout_s=WAIT_TIMEOUT_S)
            first_real_apply_button.click()
            _wait_until(page.get_by_role("link", name=re.compile(r"^(?:去冲突中心|Open Conflict Center)$")), timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("link", name=re.compile(r"^(?:去冲突中心|Open Conflict Center)$")).click()
            page.wait_for_url("**/conflicts/*", timeout=30_000)
            _wait_for_conflicts_page_ready(page, timeout_s=WAIT_TIMEOUT_S)

            _goto_with_retry(page, f"{browser_ui_base}/apply/{analyze_job_id}")
            _wait_until(page.get_by_role("heading", name=_label_pattern("Apply Confirmation", "执行确认")), timeout_s=WAIT_TIMEOUT_S)
            real_apply_button = page.get_by_role("button", name=re.compile(r"^(?:执行真实 Apply|Run Apply|Organize Now)$"))
            if real_apply_button.is_disabled():
                page.get_by_role("button", name=re.compile(r"^(?:运行 Dry-Run|Run Dry-Run|Preview Changes)$")).click()
                _wait_for_job(
                    api_base,
                    lambda item: (
                        item.get("kind") == "apply"
                        and item.get("status") == "succeeded"
                        and bool((item.get("summary") or {}).get("dry_run"))
                        and str(item.get("id") or "") != dry_run_apply_id
                        and str(((item.get("summary") or {}).get("source_manifest_path") or "")).strip() == analyze_manifest_path
                    ),
                    label="apply dry-run succeeded after conflict center jump",
                )
                _wait_for_enabled_state(real_apply_button, enabled=True, timeout_s=WAIT_TIMEOUT_S)
            real_apply_button.click()
            confirm_apply_button = page.get_by_role("button", name=re.compile(r"^(?:仍然执行|Run Anyway|Start Organizing)$"))
            _wait_until(confirm_apply_button, timeout_s=WAIT_TIMEOUT_S)
            confirm_apply_button.click()

            execute_apply = _wait_for_job(
                api_base,
                lambda item: (
                    item.get("kind") == "apply"
                    and item.get("status") == "succeeded"
                    and not bool((item.get("summary") or {}).get("dry_run"))
                    and str(((item.get("summary") or {}).get("source_manifest_path") or "")).strip() == analyze_manifest_path
                ),
                label="apply execute succeeded",
            )
            apply_job_id = str(execute_apply["id"])
            apply_summary = execute_apply.get("summary") or {}
            source_manifest_path = str(apply_summary.get("source_manifest_path") or "").strip()
            apply_manifest_path = str(apply_summary.get("manifest_path") or "").strip()
            rollback_manifest_path = str(apply_summary.get("rollback_manifest_path") or "").strip()
            assert source_manifest_path
            assert apply_manifest_path
            assert rollback_manifest_path

            _heartbeat("report")
            _goto_with_retry(page, f"{browser_ui_base}/report/{analyze_job_id}")
            _wait_for_any_visible(
                [
                    page.get_by_role("heading", name=_label_pattern("Report Insights", "报告洞察")),
                    page.get_by_role("button", name=re.compile(r"^(?:Retry loading|Retry Load|重新加载|重试加载)$")),
                ],
                timeout_s=WAIT_TIMEOUT_S,
                label="report route anchors",
            )

            _heartbeat("rollback")
            _goto_with_retry(page, f"{browser_ui_base}/rollback/{apply_job_id}")
            _wait_until(page.get_by_role("heading", name=_label_pattern("Rollback Recovery", "回滚恢复")))
            _wait_for_input_value(page.locator("#rollback-manifest"), rollback_manifest_path, timeout_s=WAIT_TIMEOUT_S)
            page.locator("#rollback-audit-reason").fill("non-live playwright e2e rollback verification")
            page.get_by_role("button", name=re.compile(r"^(?:执行 Dry-Run|Run Dry-Run|Preview Rollback)$")).click()

            _wait_for_job(
                api_base,
                lambda item: (
                    item.get("kind") == "rollback"
                    and item.get("status") == "succeeded"
                    and bool((item.get("summary") or {}).get("dry_run"))
                    and str(((item.get("summary") or {}).get("source_job_id") or "")).strip() == apply_job_id
                ),
                label="rollback dry-run succeeded",
            )

            dry_run_approved_badge = page.get_by_text(re.compile(r"^(?:Dry[- ]Run 已通过|Dry-Run Approved|Preview Approved)$"))
            rollback_execute_button = page.get_by_role("button", name=re.compile(r"^(?:执行 Rollback|Run Rollback|Roll Back Files)$"))
            _wait_for_rollback_dry_run_badge(page, timeout_s=WAIT_TIMEOUT_S)
            assert dry_run_approved_badge.is_visible(), "rollback dry-run approval did not appear in UI"

            ack_checkbox = page.get_by_label(
                re.compile(
                    r"^(?:我已确认 allowed_root 与 strict_integrity 约束，且理解回滚影响范围。|"
                    r"I confirm the allowed_root and strict_integrity constraints "
                    r"and understand the rollback blast radius\.|"
                    r"I understand the rollback scope, and I confirm the current safety boundary before continuing\.)$"
                )
            )
            assert rollback_execute_button.is_disabled()
            ack_checkbox.check(force=True)
            _wait_for_enabled_state(rollback_execute_button, enabled=True, timeout_s=WAIT_TIMEOUT_S)
            rollback_execute_button.click()

            rollback_execute = _wait_for_job(
                api_base,
                lambda item: (
                    item.get("kind") == "rollback"
                    and item.get("status") == "succeeded"
                    and not bool((item.get("summary") or {}).get("dry_run"))
                    and str(((item.get("summary") or {}).get("source_job_id") or "")).strip() == apply_job_id
                ),
                label="rollback execute succeeded",
            )
            assert str(rollback_execute["id"]).startswith("job_")

            rows_payload = _http_json(f"{api_base}/api/jobs/{apply_job_id}/manifest")
            assert isinstance(rows_payload, dict)
            raw_rows = rows_payload.get("rows")
            rows: list[object] = raw_rows if isinstance(raw_rows, list) else []
            assert rows, "apply manifest rows should not be empty"
            row0 = rows[0] if isinstance(rows[0], dict) else {}
            source_file_after = str(row0.get("path") or "").strip()
            target_file_after = str(row0.get("new_path") or "").strip()

            if source_file_after:
                _wait_for_path_state(Path(source_file_after), exists=True, timeout_s=WAIT_TIMEOUT_S)
            if target_file_after:
                _wait_for_path_state(Path(target_file_after), exists=False, timeout_s=WAIT_TIMEOUT_S)
                e2e_cleanup_actions.append(("cleanup_target_file", lambda: Path(target_file_after).unlink(missing_ok=True)))

            _heartbeat("dashboard rollback cta")
            _goto_with_retry(page, f"{browser_ui_base}/")
            _wait_for_dashboard_ready(page)
            _wait_until(page.get_by_role("link", name=_label_pattern("Rollback Guard", "打开 Rollback Guard")), timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("link", name=_label_pattern("Rollback Guard", "打开 Rollback Guard")).click()
            page.wait_for_url("**/rollback/*", timeout=30_000)
            _wait_until(page.get_by_role("heading", name=_label_pattern("Rollback Recovery", "回滚恢复")), timeout_s=WAIT_TIMEOUT_S)

            _heartbeat("job center observability")
            _open_job_center(page, timeout_s=WAIT_TIMEOUT_S)
            job_center_search = page.locator(
                "input[placeholder='搜索 job id / kind / status'], input[placeholder='Search job id / kind / status']"
            ).first
            _wait_until(job_center_search, timeout_s=WAIT_TIMEOUT_S)
            job_center_search.fill(analyze_job_id[-6:])
            analyze_job_button = page.get_by_role("button", name=analyze_job_id, exact=True)
            _wait_until(analyze_job_button, timeout_s=WAIT_TIMEOUT_S)
            analyze_job_button.click()
            _wait_until(page.get_by_text(analyze_job_id).first, timeout_s=WAIT_TIMEOUT_S)

            job_center_search.fill(apply_job_id[-6:])
            apply_job_button = page.get_by_role("button", name=apply_job_id, exact=True)
            _wait_until(apply_job_button, timeout_s=WAIT_TIMEOUT_S)
            apply_job_button.click()
            _wait_until(page.get_by_text(apply_job_id).first, timeout_s=WAIT_TIMEOUT_S)

            job_logs_level_filter = page.get_by_role("combobox").first
            _wait_until(job_logs_level_filter, timeout_s=WAIT_TIMEOUT_S)
            try:
                job_logs_level_filter.select_option("info")
                _wait_for_input_value(job_logs_level_filter, "info", timeout_s=WAIT_TIMEOUT_S)
            except Exception:
                job_logs_level_filter.click()
                info_option = page.get_by_role("option", name=re.compile(r"^info$", re.IGNORECASE)).first
                _wait_until(info_option, timeout_s=WAIT_TIMEOUT_S)
                info_option.click()

            _heartbeat("close browser")
            context.close()
            browser.close()


def test_webui_playwright_non_live_upload_conflicts_preview_and_report_filters(e2e_cleanup_actions, tmp_path: Path):
    if shutil.which("npm") is None:
        pytest.fail("webui non-live e2e requires npm in PATH")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.fail(f"webui non-live e2e requires playwright: {exc}")

    repo_root = _repo_root()
    python_bin = repo_root / ".runtime-cache" / "venv" / "default" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path(sys.executable)

    run_env = dict(os.environ)
    run_env["PYTHONUNBUFFERED"] = run_env.get("PYTHONUNBUFFERED") or "1"
    run_env["MOVI_ALLOW_HOST_EXECUTION"] = run_env.get("MOVI_ALLOW_HOST_EXECUTION") or "1"
    run_env["MOVI_IN_CONTAINER"] = run_env.get("MOVI_IN_CONTAINER") or "0"
    run_env["MOVI_ROLLBACK_HMAC_KEY"] = run_env.get("MOVI_ROLLBACK_HMAC_KEY") or "webui-playwright-e2e-key"
    run_env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{run_env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    run_env["MOVI_RUN_LIVE_TESTS"] = "0"
    run_env["MOVI_RUN_WEBUI_E2E"] = "0"
    workspace_root = tmp_path / "workspace"
    run_env["MOVI_WORKSPACE_ROOT"] = str(workspace_root)
    run_env["MOVI_INPUT_ROOT"] = str(workspace_root / "data" / "raw")
    run_env["MOVI_OUTPUT_ROOT"] = str(workspace_root / "data" / "organized")

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    api_log = log_dir / "web_api.log"

    api_port = _find_free_port()
    api_base = f"http://127.0.0.1:{api_port}"
    browser_ui_base = f"http://127.0.0.1:{api_port}/app"

    _ensure_webui_dist(repo_root, run_env, log_dir, reason="upload flow")

    with api_log.open("w", encoding="utf-8") as api_log_file:
        _heartbeat("start isolated web api server (upload flow)")
        api_proc = subprocess.Popen(
            [
                str(python_bin),
                "-m",
                "apps.api.server",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            cwd=repo_root,
            env=run_env,
            stdout=api_log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        e2e_cleanup_actions.append(
            ("terminate_web_api_upload", lambda proc=api_proc: _terminate_subprocess_safely(proc, label="web_api_upload"))
        )

        _wait_http_ready(f"{api_base}/openapi.json", timeout_s=READY_TIMEOUT_S, name="web api")
        _wait_http_ready(browser_ui_base, timeout_s=READY_TIMEOUT_S, name="static web ui")

        token = uuid.uuid4().hex[:8]
        upload_dir = tmp_path / f"upload-{token}"
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_a = upload_dir / f"upload-a-{token}.png"
        file_b = upload_dir / f"upload-b-{token}.png"
        file_c = upload_dir / f"upload-c-{token}.png"
        png = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0bIDAT\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xf4\x8f\xb6"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        file_a.write_bytes(png)
        file_b.write_bytes(png)
        file_c.write_bytes(png)

        with sync_playwright() as p:
            browser = _launch_e2e_browser(p)
            context = _new_non_live_context(browser)
            page = context.new_page()

            _heartbeat("upload flow dashboard")
            _goto_with_retry(page, f"{browser_ui_base}/")
            _wait_for_dashboard_ready(page)
            page.locator("aside").get_by_role("link", name="Analyze", exact=True).click()
            page.wait_for_url("**/analyze", timeout=30_000)
            _wait_for_analyze_ready(page)
            page.get_by_role("tab", name="Upload").click()
            page.locator("input[type='file']").first.set_input_files([str(file_a), str(file_b), str(file_c)])
            page.get_by_role("button", name="Next").click()
            step2_switches = page.get_by_role("switch")
            if step2_switches.count() > 0:
                offline_switch = step2_switches.first
                if str(offline_switch.get_attribute("aria-checked") or "").lower() != "true":
                    offline_switch.click(force=True)
                deadline = time.time() + WAIT_TIMEOUT_S
                while time.time() < deadline:
                    if str(offline_switch.get_attribute("aria-checked") or "").lower() == "true":
                        break
                    time.sleep(POLL_INTERVAL_S)
                assert str(offline_switch.get_attribute("aria-checked") or "").lower() == "true"
            else:
                step2_checkboxes = page.get_by_role("checkbox")
                if step2_checkboxes.count() > 0:
                    step2_checkboxes.first.check(force=True)
            page.get_by_role("button", name="Next").click()

            with page.expect_response(
                lambda response: response.request.method == "POST" and response.url.endswith("/api/jobs/analyze"),
                timeout=30_000,
            ) as analyze_response_info:
                page.get_by_role("button", name="Run Analyze").click()
            analyze_response = analyze_response_info.value
            assert analyze_response.status == 202
            analyze_job_id = str(analyze_response.json().get("id") or "")
            assert analyze_job_id.startswith("job_")

            _heartbeat("upload flow wait analyze job")
            _wait_for_job_id(
                api_base,
                analyze_job_id,
                expected_statuses={"succeeded"},
                timeout_s=UPLOAD_ANALYZE_WAIT_TIMEOUT_S,
                label="upload analyze succeeded",
            )

            analyze_events_payload = _http_json(f"{api_base}/api/jobs/{analyze_job_id}/events")
            event_items = analyze_events_payload.get("events") if isinstance(analyze_events_payload, dict) else analyze_events_payload
            assert isinstance(event_items, list)
            command_start_events = [
                item for item in event_items if isinstance(item, dict) and str(item.get("message") or "") == "command_start"
            ]
            assert command_start_events, "expected command_start event for analyze job"
            command_lines = [
                str((item.get("fields") or {}).get("command") or "")
                for item in command_start_events
                if isinstance(item.get("fields"), dict)
            ]
            assert any("--offline" in command for command in command_lines), (
                f"upload analyze should run with --offline in non-live e2e; got commands={command_lines!r}"
            )

            _heartbeat("upload flow manifest")
            _goto_with_retry(page, f"{browser_ui_base}/manifest/{analyze_job_id}")
            _wait_for_manifest_ready(page, timeout_s=WAIT_TIMEOUT_S)

            preview_row = _wait_for_manifest_row(page, f"upload-a-{token}.png", timeout_s=WAIT_TIMEOUT_S)
            preview_row.get_by_role("button", name=re.compile(r"^(?:操作|Actions)$")).click()
            page.get_by_role("menuitem", name=re.compile(r"^(?:预览|Preview)$")).click()
            _wait_until(page.get_by_text(re.compile(r"^(?:预览摘要|Preview Summary)$")), timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("button", name="Close", exact=True).click()

            rows_payload = _http_json(f"{api_base}/api/jobs/{analyze_job_id}/manifest")
            assert isinstance(rows_payload, dict)
            raw_rows = rows_payload.get("rows")
            rows = raw_rows if isinstance(raw_rows, list) else []
            assert len(rows) >= 3
            conflict_target = str((Path(run_env["MOVI_OUTPUT_ROOT"]).expanduser() / f"conflict-{token}.png").resolve())
            manual_target = str((Path(run_env["MOVI_OUTPUT_ROOT"]).expanduser() / f"manual-target-{token}.png").resolve())

            _http_json_request(
                f"{api_base}/api/jobs/{analyze_job_id}/manifest/batch",
                method="POST",
                payload={
                    "operations": [
                        {"row_id": "0", "patch": {"new_path": conflict_target}},
                        {"row_id": "1", "patch": {"new_path": conflict_target}},
                        {"row_id": "2", "patch": {"new_path": conflict_target}},
                    ]
                },
            )

            _heartbeat("upload flow conflicts")
            _goto_with_retry(page, f"{browser_ui_base}/conflicts/{analyze_job_id}")
            _wait_for_conflicts_page_ready(page, timeout_s=WAIT_TIMEOUT_S)
            _heartbeat("upload flow conflicts refresh")
            with (
                page.expect_response(
                    lambda response: (
                        response.request.method == "GET"
                        and bool(
                            re.search(
                                rf"/api/jobs/{re.escape(analyze_job_id)}/manifest(?:/view)?$",
                                response.url,
                            )
                        )
                    ),
                    timeout=30_000,
                ) as manifest_refresh_response,
                page.expect_response(
                    lambda response: (
                        response.request.method == "GET" and response.url.endswith(f"/api/jobs/{analyze_job_id}/manifest/conflicts")
                    ),
                    timeout=30_000,
                ) as conflicts_refresh_response,
            ):
                page.get_by_role("button", name=re.compile(r"^(?:刷新冲突|Refresh Conflicts)$")).click()
            assert manifest_refresh_response.value.status == 200
            assert conflicts_refresh_response.value.status == 200
            first_conflict_row = page.get_by_role("row").filter(has_text=f"upload-a-{token}.png").first
            _wait_until(first_conflict_row, timeout_s=WAIT_TIMEOUT_S)
            first_conflict_row.click()
            _heartbeat("upload flow conflicts preview")
            preview_related_row = page.get_by_role("button", name=re.compile(r"^(?:预览关联行|Preview Related Row)$"))
            _wait_until(preview_related_row, timeout_s=WAIT_TIMEOUT_S)
            preview_related_row.click()
            _wait_until(page.get_by_text(re.compile(r"^(?:预览摘要|Preview Summary)$")), timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("button", name="Close", exact=True).click()
            _heartbeat("upload flow conflicts manual target")
            manual_target_input = page.locator(
                "input[placeholder='手动目标路径（可选）'], "
                "input[placeholder='Manual target path (optional)'], "
                "input[placeholder='Manual target path']"
            ).first
            _wait_until(manual_target_input, timeout_s=WAIT_TIMEOUT_S)
            manual_target_input.fill(manual_target)
            manual_target_button = page.get_by_role("button", name=re.compile(r"^(?:手动目标|Use Manual Target)$"))
            _wait_until(manual_target_button, timeout_s=WAIT_TIMEOUT_S)
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST" and response.url.endswith(f"/api/jobs/{analyze_job_id}/manifest/conflicts/resolve")
                ),
                timeout=30_000,
            ) as resolve_conflict_response:
                manual_target_button.click()
            assert resolve_conflict_response.value.status == 200

            conflicts_payload = _http_json(f"{api_base}/api/jobs/{analyze_job_id}/manifest/conflicts")
            assert isinstance(conflicts_payload, dict)
            raw_conflicts = conflicts_payload.get("conflicts")
            parsed_conflicts = raw_conflicts if isinstance(raw_conflicts, list) else []
            assert parsed_conflicts, "expected conflicts for batch actions"

            select_all_conflicts = page.get_by_label(re.compile(r"^(?:选择全部冲突|Select all conflicts)$"))
            _wait_until(select_all_conflicts, timeout_s=WAIT_TIMEOUT_S)
            select_all_conflicts.check(force=True)
            page.get_by_role("button", name=re.compile(r"^(?:批量接受|Accept Selected)$")).click()
            _wait_until(
                page.get_by_text(
                    re.compile(
                        r"(?:已批量处理\s*[1-9]\d*\s*条冲突。|"
                        r"批量处理未完全成功，请重试或改为逐条处理。|"
                        r"Processed\s*[1-9]\d*\s*conflicts\.|"
                        r"Batch processing did not fully succeed\. "
                        r"Retry or handle the conflicts one by one\.)"
                    )
                ).first,
                timeout_s=60,
            )

            select_all_conflicts.check(force=True)
            page.get_by_role("button", name=re.compile(r"^(?:批量忽略|Ignore Selected)$")).click()
            _wait_until(
                page.get_by_text(
                    re.compile(
                        r"(?:已批量处理\s*[1-9]\d*\s*条冲突。|"
                        r"批量处理未完全成功，请重试或改为逐条处理。|"
                        r"Processed\s*[1-9]\d*\s*conflicts\.|"
                        r"Batch processing did not fully succeed\. "
                        r"Retry or handle the conflicts one by one\.)"
                    )
                ).first,
                timeout_s=60,
            )

            _heartbeat("upload flow report")
            _goto_with_retry(page, f"{browser_ui_base}/report/{analyze_job_id}")
            _wait_until(page.get_by_role("heading", name=_label_pattern("Report Insights", "报告洞察")))
            page.get_by_placeholder(re.compile(r"^(?:筛选报告行|Filter report rows)$")).fill("upload-a")
            _wait_until(page.get_by_text("q=upload-a"), timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("button", name=re.compile(r"^(?:清空过滤|Clear filters)$")).click()
            search_input = page.get_by_placeholder(re.compile(r"^(?:筛选报告行|Filter report rows)$"))
            _wait_until(search_input, timeout_s=WAIT_TIMEOUT_S)
            _wait_for_input_value(search_input, "", timeout_s=WAIT_TIMEOUT_S)
            report_filter_badge = page.get_by_text(re.compile("(category|media|status|error)="))
            assert report_filter_badge.count() == 0
            chart_filter_button = page.get_by_role("button", name=re.compile(r".+ · [0-9]+")).first
            _wait_until(chart_filter_button, timeout_s=WAIT_TIMEOUT_S)
            chart_filter_button.click()
            _wait_until(report_filter_badge.first, timeout_s=WAIT_TIMEOUT_S)
            chart_filter_badge_text = report_filter_badge.first.inner_text()
            matched_filter_key = re.match(r"(category|media|status|error)=", chart_filter_badge_text)
            assert matched_filter_key is not None
            chart_filter_button.click()
            filter_key = matched_filter_key.group(1)
            deadline = time.time() + WAIT_TIMEOUT_S
            while time.time() < deadline:
                if page.get_by_text(re.compile(rf"{filter_key}=")).count() == 0:
                    break
                time.sleep(POLL_INTERVAL_S)
            assert page.get_by_text(re.compile(rf"{filter_key}=")).count() == 0

            _goto_with_retry(page, f"{browser_ui_base}/report/missing-{token}")
            _wait_until(page.get_by_role("heading", name=_label_pattern("Report Insights", "报告洞察")))
            _wait_until(page.get_by_role("button", name=re.compile(r"^(?:重试加载|Retry Load|Retry loading)$")), timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("button", name=re.compile(r"^(?:重试加载|Retry Load|Retry loading)$")).click()
            _wait_until(page.get_by_role("button", name=re.compile(r"^(?:重试加载|Retry Load|Retry loading)$")), timeout_s=WAIT_TIMEOUT_S)

            _goto_with_retry(page, f"{browser_ui_base}/rollback/missing-{token}")
            _wait_until(page.get_by_role("heading", name=_label_pattern("Rollback Recovery", "回滚恢复")), timeout_s=WAIT_TIMEOUT_S)
            _wait_until(page.get_by_text(re.compile(r"^(?:Rollback 数据加载失败|Failed to Load Rollback Data)$")), timeout_s=WAIT_TIMEOUT_S)
            _wait_until(page.get_by_role("button", name=re.compile(r"^(?:重试加载|Retry Load|Retry loading)$")), timeout_s=WAIT_TIMEOUT_S)
            _wait_until(page.get_by_role("button", name=re.compile(r"^(?:恢复默认值|Restore Defaults)$")), timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("button", name=re.compile(r"^(?:恢复默认值|Restore Defaults)$")).click()
            deadline = time.time() + WAIT_TIMEOUT_S
            while time.time() < deadline:
                if page.get_by_text(re.compile(r"^(?:Rollback 数据加载失败|Failed to Load Rollback Data)$")).count() == 0:
                    break
                time.sleep(POLL_INTERVAL_S)
            assert page.get_by_text(re.compile(r"^(?:Rollback 数据加载失败|Failed to Load Rollback Data)$")).count() == 0

            _heartbeat("upload flow job center")
            _open_job_center(page, timeout_s=WAIT_TIMEOUT_S)
            _wait_until(page.get_by_role("heading", name=_label_pattern("Job Center", "作业中心")), timeout_s=WAIT_TIMEOUT_S)
            job_center_search = page.locator(
                "input[placeholder='搜索 job id / kind / status'], input[placeholder='Search job id / kind / status']"
            ).first
            _wait_until(job_center_search, timeout_s=WAIT_TIMEOUT_S)
            job_center_search.fill(analyze_job_id[-6:])
            _wait_until(page.get_by_role("button", name=analyze_job_id, exact=True), timeout_s=WAIT_TIMEOUT_S)

            _heartbeat("upload flow jobs")
            _close_job_center(page, timeout_s=WAIT_TIMEOUT_S)
            _goto_with_retry(page, f"{browser_ui_base}/jobs")
            page.wait_for_url("**/jobs", timeout=30_000)
            _wait_for_jobs_ready(page, timeout_s=WAIT_TIMEOUT_S)
            page.locator(
                "input[placeholder='搜索 job id / phase / status'], input[placeholder='Search job id / phase / status']"
            ).first.fill(analyze_job_id[-6:])
            target_row = page.get_by_role("row").filter(has_text=analyze_job_id).first
            _wait_until(target_row, timeout_s=WAIT_TIMEOUT_S)
            _heartbeat("upload flow jobs logs")
            _ensure_checkbox_selected(
                target_row.get_by_role("checkbox").first,
                timeout_s=WAIT_TIMEOUT_S,
            )
            _wait_until(page.get_by_role("combobox").first, timeout_s=WAIT_TIMEOUT_S)
            _heartbeat("upload flow jobs manifest jump")
            target_row.get_by_role("link", name=re.compile(r"^(?:Review|进入 Review)$")).click()
            page.wait_for_url("**/review/*", timeout=30_000)
            _wait_for_manifest_ready(page, timeout_s=WAIT_TIMEOUT_S)
            _goto_with_retry(page, f"{browser_ui_base}/jobs")
            _wait_for_jobs_ready(page, timeout_s=WAIT_TIMEOUT_S)
            target_row = page.get_by_role("row").filter(has_text=analyze_job_id).first
            _wait_until(target_row, timeout_s=WAIT_TIMEOUT_S)
            _ensure_checkbox_selected(
                page.get_by_role(
                    "checkbox",
                    name=re.compile(rf"^(?:Select {re.escape(analyze_job_id)}|选择作业 {re.escape(analyze_job_id)})$"),
                ),
                timeout_s=WAIT_TIMEOUT_S,
            )
            _wait_until(page.get_by_role("button", name=re.compile(r"^(?:Retry Job|重试作业)$")), timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("button", name=re.compile(r"^(?:Retry Job|重试作业)$")).click()
            _wait_until(
                page.get_by_role("status").get_by_text(re.compile(r"^(?:Retry request submitted\.|已提交重试请求。)$")),
                timeout_s=WAIT_TIMEOUT_S,
            )
            _wait_for_job(
                api_base,
                lambda item: item.get("kind") == "analyze" and item.get("retry_of") == analyze_job_id,
                label="jobs retry created",
            )

            def _mock_retry_failure(route):
                route.fulfill(status=500, headers={"content-type": "application/json"}, body='{"detail":"retry blocked for e2e"}')

            retry_route_pattern = re.compile(r".*/api/jobs/.*/retry$")
            page.route(retry_route_pattern, _mock_retry_failure)
            try:
                page.get_by_role("button", name=re.compile(r"^(?:Retry Job|重试作业)$")).click()
                _wait_until(
                    page.get_by_role("status").get_by_text(re.compile("retry blocked for e2e|Retry job failed")),
                    timeout_s=WAIT_TIMEOUT_S,
                )
            finally:
                page.unroute(retry_route_pattern, _mock_retry_failure)

            context.close()
            browser.close()


def test_webui_playwright_non_live_jobs_cancel(e2e_cleanup_actions, tmp_path: Path):
    if shutil.which("npm") is None:
        pytest.fail("webui non-live e2e requires npm in PATH")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.fail(f"webui non-live e2e requires playwright: {exc}")

    repo_root = _repo_root()
    python_bin = repo_root / ".runtime-cache" / "venv" / "default" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path(sys.executable)

    run_env = dict(os.environ)
    run_env["PYTHONUNBUFFERED"] = run_env.get("PYTHONUNBUFFERED") or "1"
    run_env["MOVI_ALLOW_HOST_EXECUTION"] = run_env.get("MOVI_ALLOW_HOST_EXECUTION") or "1"
    run_env["MOVI_IN_CONTAINER"] = run_env.get("MOVI_IN_CONTAINER") or "0"
    run_env["MOVI_ROLLBACK_HMAC_KEY"] = run_env.get("MOVI_ROLLBACK_HMAC_KEY") or "webui-playwright-e2e-key"
    run_env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{run_env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    run_env["MOVI_RUN_LIVE_TESTS"] = "0"
    run_env["MOVI_RUN_WEBUI_E2E"] = "0"
    workspace_root = tmp_path / "workspace"
    run_env["MOVI_WORKSPACE_ROOT"] = str(workspace_root)
    run_env["MOVI_INPUT_ROOT"] = str(workspace_root / "data" / "raw")
    run_env["MOVI_OUTPUT_ROOT"] = str(workspace_root / "data" / "organized")

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    api_log = log_dir / "slow_web_api.log"

    api_port = _find_free_port()
    api_base = f"http://127.0.0.1:{api_port}"
    browser_ui_base = f"http://127.0.0.1:{api_port}/app"

    token = uuid.uuid4().hex[:8]
    source_dir = Path(run_env["MOVI_INPUT_ROOT"]) / f"cancel-source-{token}"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "cancel-me.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0bIDAT\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xf4\x8f\xb6"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    e2e_cleanup_actions.append(("cleanup_cancel_source_dir", lambda: shutil.rmtree(source_dir, ignore_errors=True)))
    _write_slow_api_module(tmp_path)
    _ensure_webui_dist(repo_root, run_env, log_dir, reason="cancel flow")

    with api_log.open("w", encoding="utf-8") as api_log_file:
        api_proc = subprocess.Popen(
            [
                str(python_bin),
                "-m",
                "uvicorn",
                "--app-dir",
                str(tmp_path),
                "slow_web_api_app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            cwd=repo_root,
            env=run_env,
            stdout=api_log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        e2e_cleanup_actions.append(
            ("terminate_web_api_cancel", lambda proc=api_proc: _terminate_subprocess_safely(proc, label="web_api_cancel"))
        )
        _wait_http_ready(f"{api_base}/openapi.json", timeout_s=READY_TIMEOUT_S, name="slow web api")
        _wait_http_ready(browser_ui_base, timeout_s=READY_TIMEOUT_S, name="static web ui")

        with sync_playwright() as p:
            browser = _launch_e2e_browser(p)
            context = _new_non_live_context(browser)
            page = context.new_page()

            _goto_with_retry(page, f"{browser_ui_base}/")
            _wait_for_dashboard_ready(page)
            page.get_by_role("link", name=_label_pattern("Analyze", "分析")).click()
            page.wait_for_url("**/analyze", timeout=30_000)
            _wait_for_analyze_ready(page)
            page.locator("#dir-path").fill(str(source_dir))
            page.get_by_role("button", name="Next").click()
            step2_checkboxes = page.get_by_role("checkbox")
            if step2_checkboxes.count() > 0:
                step2_checkboxes.first.check(force=True)
            page.get_by_role("button", name="Next").click()

            with page.expect_response(
                lambda response: response.request.method == "POST" and response.url.endswith("/api/jobs/analyze"),
                timeout=30_000,
            ) as analyze_response_info:
                page.get_by_role("button", name="Run Analyze").click()
            analyze_job_id = str(analyze_response_info.value.json().get("id") or "")
            assert analyze_job_id.startswith("job_")

            _wait_for_job_id(
                api_base,
                analyze_job_id,
                expected_statuses={"running", "cancelling"},
                label="jobs cancel analyze running",
            )

            _goto_with_retry(page, f"{browser_ui_base}/jobs")
            _wait_for_jobs_ready(page, timeout_s=WAIT_TIMEOUT_S)
            target_row = page.get_by_role("row").filter(has_text=analyze_job_id).first
            _wait_until(target_row, timeout_s=WAIT_TIMEOUT_S)
            _ensure_checkbox_selected(
                page.get_by_role(
                    "checkbox",
                    name=re.compile(rf"^(?:Select {re.escape(analyze_job_id)}|选择作业 {re.escape(analyze_job_id)})$"),
                ),
                timeout_s=WAIT_TIMEOUT_S,
            )
            current_job_card = page.get_by_test_id("current-job-card")
            cancel_button = current_job_card.get_by_test_id("current-job-cancel")
            _wait_until(cancel_button, timeout_s=WAIT_TIMEOUT_S)
            _wait_for_enabled_state(cancel_button, enabled=True, timeout_s=WAIT_TIMEOUT_S)
            with page.expect_response(
                lambda response: response.url.endswith(f"/api/jobs/{analyze_job_id}/cancel"),
                timeout=30_000,
            ) as cancel_response_info:
                cancel_button.click(force=True)
            cancel_response = cancel_response_info.value
            assert cancel_response.status == 200
            cancel_payload = cancel_response.json()
            assert str(cancel_payload.get("id") or "") == analyze_job_id
            assert str(cancel_payload.get("status") or "") in {"cancelling", "cancelled", "succeeded", "failed"}
            _wait_until(
                page.get_by_role("status").get_by_text(re.compile(r"^(?:Cancel request submitted\.|已提交取消请求。)$")),
                timeout_s=WAIT_TIMEOUT_S,
            )

            terminal_job = _wait_for_job_id(
                api_base,
                analyze_job_id,
                expected_statuses={"cancelled", "succeeded", "failed"},
                label="jobs cancel terminal",
            )
            if terminal_job.get("status") != "cancelled":
                assert terminal_job.get("cancel_requested_at"), terminal_job

            context.close()
            browser.close()
