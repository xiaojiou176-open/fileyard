from __future__ import annotations

import atexit
import errno
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

LIVE_FLAG = "FILEORGANIZE_RUN_LIVE_TESTS"
WEBUI_E2E_FLAG = "FILEORGANIZE_RUN_WEBUI_E2E"
WAIT_TIMEOUT_S = 180
READY_TIMEOUT_S = 60
POLL_INTERVAL_S = 0.3

_LIVE_PROCESS_KEYWORDS = ("pytest", "uvicorn", "vite", "playwright", "chromium", "chrome", "ms-playwright", "node")
_LIVE_COVERAGE_GUARD_ENABLED = False
_LIVE_COVERAGE_HAD_BASELINE = False
_LIVE_COVERAGE_BACKUP_PATH: Path | None = None
_LIVE_COVERAGE_DATA_HAD_BASELINE = False
_LIVE_COVERAGE_DATA_BACKUP_PATH: Path | None = None
_LIVE_COVERAGE_DATA_ISOLATED_PATH: Path | None = None
_LIVE_PREVIOUS_COVERAGE_FILE: str | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _workspace_input_root() -> Path:
    return Path(os.environ.get("FILEORGANIZE_INPUT_ROOT", "~/.fileorganize/workspaces/default/data/raw")).expanduser()


def _workspace_output_root() -> Path:
    return Path(os.environ.get("FILEORGANIZE_OUTPUT_ROOT", "~/.fileorganize/workspaces/default/data/organized")).expanduser()


def _is_live_env_requested() -> bool:
    return os.getenv(LIVE_FLAG, "").strip() == "1" and os.getenv(WEBUI_E2E_FLAG, "").strip() == "1"


def _restore_live_coverage_truth() -> None:
    global _LIVE_COVERAGE_GUARD_ENABLED
    if not _LIVE_COVERAGE_GUARD_ENABLED:
        return
    _LIVE_COVERAGE_GUARD_ENABLED = False
    coverage_xml = _repo_root() / "artifacts" / "coverage.xml"
    coverage_data = _repo_root() / ".coverage"
    try:
        if _LIVE_COVERAGE_HAD_BASELINE and _LIVE_COVERAGE_BACKUP_PATH and _LIVE_COVERAGE_BACKUP_PATH.exists():
            coverage_xml.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_LIVE_COVERAGE_BACKUP_PATH, coverage_xml)
        elif coverage_xml.exists():
            coverage_xml.unlink()
        if _LIVE_COVERAGE_DATA_HAD_BASELINE and _LIVE_COVERAGE_DATA_BACKUP_PATH and _LIVE_COVERAGE_DATA_BACKUP_PATH.exists():
            shutil.copy2(_LIVE_COVERAGE_DATA_BACKUP_PATH, coverage_data)
        elif coverage_data.exists():
            coverage_data.unlink()
    except Exception:
        pass
    finally:
        if _LIVE_COVERAGE_BACKUP_PATH and _LIVE_COVERAGE_BACKUP_PATH.exists():
            try:
                _LIVE_COVERAGE_BACKUP_PATH.unlink()
            except Exception:
                pass
        if _LIVE_COVERAGE_DATA_BACKUP_PATH and _LIVE_COVERAGE_DATA_BACKUP_PATH.exists():
            try:
                _LIVE_COVERAGE_DATA_BACKUP_PATH.unlink()
            except Exception:
                pass
        if _LIVE_COVERAGE_DATA_ISOLATED_PATH:
            for suffix in ("", "-shm", "-wal"):
                path = Path(f"{_LIVE_COVERAGE_DATA_ISOLATED_PATH}{suffix}")
                if path.exists():
                    try:
                        path.unlink()
                    except Exception:
                        pass
        for suffix in ("-shm", "-wal"):
            sidecar = Path(f"{coverage_data}{suffix}")
            if sidecar.exists():
                try:
                    sidecar.unlink()
                except Exception:
                    pass
        if _LIVE_PREVIOUS_COVERAGE_FILE is None:
            os.environ.pop("COVERAGE_FILE", None)
        else:
            os.environ["COVERAGE_FILE"] = _LIVE_PREVIOUS_COVERAGE_FILE


def _activate_live_coverage_guard() -> None:
    global _LIVE_COVERAGE_GUARD_ENABLED
    global _LIVE_COVERAGE_HAD_BASELINE, _LIVE_COVERAGE_BACKUP_PATH
    global _LIVE_COVERAGE_DATA_HAD_BASELINE, _LIVE_COVERAGE_DATA_BACKUP_PATH
    global _LIVE_COVERAGE_DATA_ISOLATED_PATH, _LIVE_PREVIOUS_COVERAGE_FILE
    if not _is_live_env_requested() or _LIVE_COVERAGE_GUARD_ENABLED:
        return
    coverage_xml = _repo_root() / "artifacts" / "coverage.xml"
    coverage_data = _repo_root() / ".coverage"
    _LIVE_COVERAGE_HAD_BASELINE = coverage_xml.exists()
    _LIVE_COVERAGE_BACKUP_PATH = Path(tempfile.gettempdir()) / f"fileorganize-live-coverage-{os.getpid()}.xml"
    if _LIVE_COVERAGE_HAD_BASELINE:
        _LIVE_COVERAGE_BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(coverage_xml, _LIVE_COVERAGE_BACKUP_PATH)
    else:
        if _LIVE_COVERAGE_BACKUP_PATH.exists():
            _LIVE_COVERAGE_BACKUP_PATH.unlink()
    _LIVE_COVERAGE_DATA_HAD_BASELINE = coverage_data.exists()
    _LIVE_COVERAGE_DATA_BACKUP_PATH = Path(tempfile.gettempdir()) / f"fileorganize-live-coverage-data-{os.getpid()}"
    if _LIVE_COVERAGE_DATA_HAD_BASELINE:
        _LIVE_COVERAGE_DATA_BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(coverage_data, _LIVE_COVERAGE_DATA_BACKUP_PATH)
    elif _LIVE_COVERAGE_DATA_BACKUP_PATH.exists():
        _LIVE_COVERAGE_DATA_BACKUP_PATH.unlink()
    _LIVE_COVERAGE_DATA_ISOLATED_PATH = Path(tempfile.gettempdir()) / f"fileorganize-live-cov-isolated-{os.getpid()}"
    _LIVE_PREVIOUS_COVERAGE_FILE = os.environ.get("COVERAGE_FILE")
    os.environ["COVERAGE_FILE"] = str(_LIVE_COVERAGE_DATA_ISOLATED_PATH)
    for suffix in ("", "-shm", "-wal"):
        path = Path(f"{_LIVE_COVERAGE_DATA_ISOLATED_PATH}{suffix}")
        if path.exists():
            path.unlink()
    _LIVE_COVERAGE_GUARD_ENABLED = True
    atexit.register(_restore_live_coverage_truth)


def _collect_parent_map() -> dict[int, int]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}
    parent_by_pid: dict[int, int] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        parent_by_pid[pid] = ppid
    return parent_by_pid


def _collect_ancestor_pids() -> set[int]:
    parent_by_pid = _collect_parent_map()
    current = os.getpid()
    ancestors: set[int] = {current}
    while True:
        parent = parent_by_pid.get(current)
        if parent is None or parent <= 1 or parent in ancestors:
            break
        ancestors.add(parent)
        current = parent
    return ancestors


def _list_repo_residual_processes(repo_root: Path) -> list[tuple[int, str]]:
    repo_marker = str(repo_root.resolve())
    ancestors = _collect_ancestor_pids()
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    matches: list[tuple[int, str]] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        command = parts[1]
        lower_cmd = command.lower()
        if pid in ancestors:
            continue
        if repo_marker not in command:
            continue
        if not any(keyword in lower_cmd for keyword in _LIVE_PROCESS_KEYWORDS):
            continue
        matches.append((pid, command))
    return matches


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        return False
    return True


def _cleanup_repo_live_processes(repo_root: Path) -> None:
    matches = _list_repo_residual_processes(repo_root)
    if not matches:
        _heartbeat("preflight process cleanup: no stale repo processes found")
        return
    _heartbeat(f"preflight process cleanup: terminating {len(matches)} stale repo process(es)")
    for pid, command in matches:
        _heartbeat(f"terminate stale pid={pid} cmd={command[:180]}")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError:
            continue
    deadline = time.time() + 3.0
    while time.time() < deadline:
        alive = [pid for pid, _ in matches if _is_pid_alive(pid)]
        if not alive:
            return
        time.sleep(0.1)
    for pid, command in matches:
        if not _is_pid_alive(pid):
            continue
        _heartbeat(f"force kill stale pid={pid} cmd={command[:180]}")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue
        except PermissionError:
            continue


_activate_live_coverage_guard()


def _read_runtime_env_value(name: str) -> str:
    workspace_root = Path(os.getenv("FILEORGANIZE_WORKSPACE_ROOT", "~/.fileorganize/workspaces/default")).expanduser()
    env_path = workspace_root / ".fileorganize" / "env" / "runtime.env"
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


def _resolve_live_var(name: str, default: str = "") -> str:
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
    return _resolve_live_var(LIVE_FLAG, "0") == "1" and _resolve_live_var(WEBUI_E2E_FLAG, "0") == "1"


@pytest.fixture(autouse=True)
def _restore_live_env_vars():
    keys = (LIVE_FLAG, WEBUI_E2E_FLAG)
    snapshot = {key: os.environ.get(key) for key in keys}
    yield
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def live_cleanup_actions():
    actions: list[tuple[str, Callable[[], None]]] = []
    yield actions
    failures: list[str] = []
    for label, callback in reversed(actions):
        try:
            callback()
        except Exception as exc:  # pragma: no cover - cleanup is environment dependent
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
    if failures:
        pytest.fail("webui_live_e2e teardown failed: " + "; ".join(failures))


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _is_port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _heartbeat(message: str) -> None:
    print(f"[webui-live-e2e] {message}", flush=True)


def _http_status(url: str) -> int:
    try:
        with urlopen(url, timeout=5) as response:
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)
    except URLError:
        return 0


def _http_json(url: str) -> dict | list:
    last_error: Exception | None = None
    for _ in range(5):
        try:
            with urlopen(url, timeout=10) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            last_error = exc
            time.sleep(POLL_INTERVAL_S)
    assert last_error is not None
    raise last_error


def _http_json_request(url: str, *, method: str, payload: dict) -> dict | list:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {url} failed: status={exc.code} body={detail}") from exc


def _extract_app_asset_paths(index_html: str) -> list[str]:
    candidates = re.findall(r"""(?:src|href)=["'](/app/assets/[^"']+)["']""", index_html)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _wait_http_ready(url: str, timeout_s: int, name: str) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _http_status(url)
        if 200 <= status < 500:
            return
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"{name} not ready within {timeout_s}s: {url}")


def _loopback_url_variants(url: str) -> list[str]:
    variants = [url]
    if "://127.0.0.1" in url:
        variants.append(url.replace("://127.0.0.1", "://localhost", 1))
    elif "://localhost" in url:
        variants.append(url.replace("://localhost", "://127.0.0.1", 1))
    deduped: list[str] = []
    for candidate in variants:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _goto_with_retry(page, url: str, *, wait_until: str = "commit", timeout_ms: int = 30_000, attempts: int = 5) -> None:
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


def _wait_for_job(
    api_base: str,
    predicate: Callable[[dict], bool],
    *,
    timeout_s: int = WAIT_TIMEOUT_S,
    label: str,
) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            payload = _http_json(f"{api_base}/api/jobs")
        except (URLError, OSError):
            time.sleep(POLL_INTERVAL_S)
            continue
        assert isinstance(payload, list)
        for item in payload:
            if isinstance(item, dict) and predicate(item):
                return item
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"timed out waiting for job: {label}")


def _wait_until(locator, *, timeout_s: int = WAIT_TIMEOUT_S) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if locator.is_visible():
            return
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"locator not visible within {timeout_s}s")


def _wait_for_any_visible(locators: list, *, timeout_s: int, label: str) -> None:
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


def _wait_for_dashboard_ready(page, *, timeout_s: int = WAIT_TIMEOUT_S) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        probe_timeout = min(20, max(5, int(deadline - time.time())))
        sidebar = page.locator("aside")
        try:
            _wait_for_any_visible(
                [
                    sidebar.get_by_role("link", name="Analyze", exact=True),
                    page.get_by_role("button", name="Job Center", exact=True),
                ],
                timeout_s=probe_timeout,
                label="app-shell anchors",
            )
            _wait_for_any_visible(
                [
                    page.get_by_role("link", name="Start Analyze", exact=True),
                    page.get_by_role("link", name="4-step guided flow", exact=True),
                    page.get_by_role("link", name="Jobs History", exact=True),
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
            if home_url:
                try:
                    _goto_with_retry(page, home_url, wait_until="commit", timeout_ms=15_000, attempts=2)
                except Exception:
                    pass
            else:
                try:
                    page.reload(wait_until="commit", timeout=15_000)
                except Exception:
                    pass
            time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"dashboard not ready within {timeout_s}s: url={page.url} last_error={last_error}")


def _wait_for_input_value(locator, expected: str, *, timeout_s: int = WAIT_TIMEOUT_S) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if locator.input_value() == expected:
                return
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"input value did not become {expected!r} within {timeout_s}s")


def _wait_for_enabled_state(locator, *, enabled: bool, timeout_s: int = WAIT_TIMEOUT_S) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if locator.is_enabled() is enabled:
                return
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"locator enabled state did not become {enabled} within {timeout_s}s")


def _wait_for_path_state(path: Path, *, exists: bool, timeout_s: int = WAIT_TIMEOUT_S) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.exists() is exists:
            return
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"path state did not become exists={exists}: {path}")


def _launch_live_browser(playwright):
    ci_hosted = os.getenv("CI", "").strip().lower() in {"1", "true"} or os.getenv("GITHUB_ACTIONS", "").strip().lower() == "true"
    try:
        if ci_hosted:
            return playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-proxy-server",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
        return playwright.webkit.launch(headless=True)
    except Exception:
        try:
            return playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-proxy-server",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
        except Exception:
            return playwright.chromium.launch(headless=True)


def _open_dashboard_with_retry(playwright, browser_ui_base: str, *, attempts: int = 2):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        browser = _launch_live_browser(playwright)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        try:
            _heartbeat(f"open dashboard root attempt={attempt}/{attempts}")
            _goto_with_retry(page, f"{browser_ui_base}/")
            _wait_for_dashboard_ready(page, timeout_s=min(WAIT_TIMEOUT_S, 90))
            return browser, context, page
        except Exception as exc:
            last_error = exc
            _heartbeat(f"dashboard root retry attempt={attempt}/{attempts} failed: {type(exc).__name__}: {exc}")
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            if attempt >= attempts:
                raise
    assert last_error is not None
    raise last_error


@pytest.mark.live_browser
def test_live_webui_env_preflight():
    # test-quality: allow-no-assert
    if not _resolve_live_var(LIVE_FLAG, "0") == "1":
        pytest.skip(f"set {LIVE_FLAG}=1 to run live browser tests")
    if not _resolve_live_var(WEBUI_E2E_FLAG, "0") == "1":
        pytest.skip(f"set {WEBUI_E2E_FLAG}=1 to run Fileorganize WebUI live e2e")
    if shutil.which("npm") is None:
        pytest.fail("webui live e2e requires npm")


@pytest.mark.live_browser
def test_live_webui_analyze_manifest_apply_rollback(live_cleanup_actions, tmp_path: Path):
    if not _is_live_enabled():
        pytest.skip(f"set {LIVE_FLAG}=1 and {WEBUI_E2E_FLAG}=1 to run Fileorganize WebUI live e2e")

    if shutil.which("npm") is None:
        pytest.fail("webui live e2e requires npm in PATH")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.fail(f"webui live e2e enabled but playwright is unavailable: {exc}")

    repo_root = _repo_root()
    _cleanup_repo_live_processes(repo_root)
    python_bin = repo_root / ".runtime-cache" / "venv" / "default" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path(sys.executable)

    run_env = os.environ.copy()
    run_env["PYTHONUNBUFFERED"] = run_env.get("PYTHONUNBUFFERED") or "1"
    run_env["FILEORGANIZE_ALLOW_HOST_EXECUTION"] = run_env.get("FILEORGANIZE_ALLOW_HOST_EXECUTION") or "1"
    run_env["FILEORGANIZE_IN_CONTAINER"] = run_env.get("FILEORGANIZE_IN_CONTAINER") or "0"
    run_env["FILEORGANIZE_ROLLBACK_HMAC_KEY"] = run_env.get("FILEORGANIZE_ROLLBACK_HMAC_KEY") or "webui-live-e2e-key"

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    api_log = log_dir / "web_api.log"
    ui_log = log_dir / "vite.log"

    build_ready = False
    _heartbeat("build webui dist for static-host readiness precheck")
    try:
        subprocess.run(["npm", "run", "build"], cwd=repo_root, env=run_env, check=True)
        build_ready = True
    except subprocess.CalledProcessError as exc:
        _heartbeat(f"build precheck failed (non-blocking for this live e2e): exit={exc.returncode}")

    api_port = _find_free_port()
    ui_port = _find_free_port()
    api_base = f"http://127.0.0.1:{api_port}"
    ui_base = f"http://127.0.0.1:{ui_port}"
    browser_ui_base = f"{api_base}/app" if build_ready else ui_base
    run_env["FILEORGANIZE_WEB_API_PROXY_TARGET"] = api_base

    with api_log.open("w", encoding="utf-8") as api_log_file, ui_log.open("w", encoding="utf-8") as ui_log_file:
        _heartbeat("start isolated fileorganize web api")
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
        )
        live_cleanup_actions.append(("wait_web_api", lambda: api_proc.wait(timeout=10)))
        live_cleanup_actions.append(("terminate_web_api", lambda: api_proc.terminate()))

        _wait_http_ready(f"{api_base}/openapi.json", timeout_s=READY_TIMEOUT_S, name="web api")

        if build_ready:
            app_html = ""
            try:
                with urlopen(f"{api_base}/app/", timeout=10) as response:
                    app_html = response.read().decode("utf-8")
            except Exception as exc:
                pytest.fail(f"web api static host probe failed: {exc}")
            asset_paths = _extract_app_asset_paths(app_html)
            assert asset_paths, "web api /app should expose hashed /app/assets/* entries in index.html"
            for path in asset_paths[:4]:
                status = _http_status(f"{api_base}{path}")
                assert status == 200, f"static asset should be reachable: {path} status={status}"
            _wait_http_ready(f"{browser_ui_base}/", timeout_s=READY_TIMEOUT_S, name="static web ui")

        if build_ready:
            _heartbeat("use web api static app host for browser routing")
        else:
            _heartbeat("start vite dev server for stable browser routing")
            ui_proc = subprocess.Popen(
                ["npm", "--prefix", "apps/webui", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(ui_port)],
                cwd=repo_root,
                env=run_env,
                stdout=ui_log_file,
                stderr=subprocess.STDOUT,
            )
            live_cleanup_actions.append(("wait_vite", lambda: ui_proc.wait(timeout=10)))
            live_cleanup_actions.append(("terminate_vite", lambda: ui_proc.terminate()))

            _wait_http_ready(f"{ui_base}/", timeout_s=READY_TIMEOUT_S, name="vite ui")

        unique_token = uuid.uuid4().hex[:8]
        unique_name = f"e2e-webui-{unique_token}.png"
        source_dir = _workspace_input_root() / f"e2e-live-{unique_token}"
        source_dir.mkdir(parents=True, exist_ok=True)
        source_file = source_dir / unique_name
        source_file.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0bIDAT\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xf4\x8f\xb6"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        live_cleanup_actions.append(("cleanup_source_dir", lambda: shutil.rmtree(source_dir, ignore_errors=True)))

        with sync_playwright() as p:
            browser, context, page = _open_dashboard_with_retry(p, browser_ui_base)
            _heartbeat("navigate to analyze from dashboard")
            page.get_by_role("link", name="Analyze", exact=True).click()
            page.wait_for_url("**/analyze", timeout=30_000)
            _wait_until(page.get_by_role("heading", name="Analyze Wizard"))

            _heartbeat("step 1 directory mode")
            page.locator("#dir-path").fill(str(source_dir))
            page.get_by_role("button", name="Next").click()

            _heartbeat("step 2 enable offline")
            step2_switches = page.get_by_role("switch")
            if step2_switches.count() > 0:
                step2_switches.first.click(force=True)
            else:
                step2_checkboxes = page.get_by_role("checkbox")
                if step2_checkboxes.count() > 0:
                    step2_checkboxes.first.check(force=True)
            page.get_by_role("button", name="Next").click()

            _heartbeat("step 3 run analyze")
            with page.expect_response(lambda response: response.url.endswith("/api/jobs/analyze"), timeout=30_000) as analyze_response_info:
                page.get_by_role("button", name="Run Analyze").click()
            analyze_response = analyze_response_info.value
            assert analyze_response.status == 202
            analyze_payload = analyze_response.json()
            analyze_job_id = str(analyze_payload.get("id") or "")
            assert analyze_job_id.startswith("job_")
            _wait_for_job(
                api_base,
                lambda item: item.get("id") == analyze_job_id and item.get("status") == "succeeded",
                label="analyze succeeded",
            )
            _heartbeat("open jobs runtime and verify analyze job via API without dropdown dependency")
            page.goto(f"{browser_ui_base}/jobs", wait_until="commit", timeout=30_000)
            _wait_until(page.get_by_role("heading", name="Jobs Runtime"))
            jobs_search = page.get_by_placeholder("Search job id / phase / status")
            jobs_search.fill(analyze_job_id)
            _wait_for_input_value(jobs_search, analyze_job_id, timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("button", name="Refresh").first.click()
            jobs_payload = _http_json(f"{api_base}/api/jobs")
            assert isinstance(jobs_payload, list)
            assert any(isinstance(item, dict) and item.get("id") == analyze_job_id for item in jobs_payload)
            page.goto(f"{browser_ui_base}/manifest/{analyze_job_id}", wait_until="commit", timeout=30_000)
            _wait_until(page.get_by_role("heading", name=re.compile(r"^(?:Manifest 编辑工作台|Manifest Workbench)$")))
            _wait_until(page.get_by_text(unique_name, exact=False), timeout_s=WAIT_TIMEOUT_S)

            analyze_job = _http_json(f"{api_base}/api/jobs/{analyze_job_id}")
            assert isinstance(analyze_job, dict)
            analyze_manifest_path = str(((analyze_job.get("summary") or {}).get("manifest_path") or "")).strip()
            assert analyze_manifest_path

            manifest_rows_payload = _http_json(f"{api_base}/api/jobs/{analyze_job_id}/manifest")
            assert isinstance(manifest_rows_payload, dict)
            manifest_rows = manifest_rows_payload.get("rows") if isinstance(manifest_rows_payload.get("rows"), list) else []
            assert manifest_rows, "manifest rows should not be empty after analyze"
            first_row = manifest_rows[0] if isinstance(manifest_rows[0], dict) else {}
            first_row_id = str(first_row.get("row_id") or "0")
            execute_target = str((_workspace_output_root() / f"e2e-live-{unique_token}-renamed.png").resolve())
            _http_json_request(
                f"{api_base}/api/jobs/{analyze_job_id}/manifest/batch",
                method="POST",
                payload={
                    "operations": [
                        {"row_id": first_row_id, "patch": {"new_path": execute_target}},
                    ]
                },
            )

            _heartbeat("go to apply and run dry-run")
            apply_link = page.get_by_role("link", name="Open Apply Dry-Run")
            _wait_until(apply_link, timeout_s=WAIT_TIMEOUT_S)
            apply_href = str(apply_link.get_attribute("href") or "").strip()
            assert apply_href.endswith(f"/apply/{analyze_job_id}")
            page.goto(f"{browser_ui_base}/apply/{analyze_job_id}", wait_until="commit", timeout=30_000)
            page.wait_for_url("**/apply/*", timeout=30_000)
            _wait_until(page.get_by_role("heading", name="Apply Confirmation"))
            page.get_by_role("button", name="Preview Changes").click()

            dry_run_apply = _wait_for_job(
                api_base,
                lambda item: (
                    item.get("kind") == "apply"
                    and item.get("status") == "succeeded"
                    and bool((item.get("summary") or {}).get("dry_run"))
                    and str((item.get("summary") or {}).get("source_manifest_path") or "").strip() == analyze_manifest_path
                ),
                label="apply dry-run succeeded",
            )
            assert dry_run_apply["id"].startswith("job_")

            _heartbeat("execute apply")
            page.get_by_role("button", name="Organize Now").click()
            page.get_by_role("button", name="Start Organizing").click()

            execute_apply = _wait_for_job(
                api_base,
                lambda item: (
                    item.get("kind") == "apply"
                    and item.get("status") == "succeeded"
                    and not bool((item.get("summary") or {}).get("dry_run"))
                    and str((item.get("summary") or {}).get("source_manifest_path") or "").strip() == analyze_manifest_path
                ),
                label="apply execute succeeded",
            )
            apply_job_id = str(execute_apply["id"])
            apply_summary = execute_apply.get("summary") or {}
            apply_manifest_path = str(apply_summary.get("manifest_path") or "").strip()
            rollback_manifest_path = str(apply_summary.get("rollback_manifest_path") or "").strip()
            assert apply_manifest_path
            assert rollback_manifest_path

            rows_payload = _http_json(f"{api_base}/api/jobs/{apply_job_id}/manifest")
            assert isinstance(rows_payload, dict)
            rows = rows_payload.get("rows") if isinstance(rows_payload.get("rows"), list) else []
            assert rows, "apply manifest rows should not be empty"
            row0 = rows[0] if isinstance(rows[0], dict) else {}
            source_path = str(row0.get("path") or "").strip()
            target_path = str(row0.get("new_path") or "").strip()

            conflicts_payload = _http_json(f"{api_base}/api/jobs/{analyze_job_id}/manifest/conflicts")
            assert isinstance(conflicts_payload, dict)
            assert isinstance(conflicts_payload.get("conflicts"), list)

            row_id = str(row0.get("row_id") or "0").strip() or "0"
            preview_status = _http_status(f"{api_base}/api/jobs/{apply_job_id}/manifest/{row_id}/preview")
            assert preview_status == 200, f"preview endpoint should be reachable for row_id={row_id}"

            _heartbeat("open report and exercise filter interactions")
            page.goto(f"{browser_ui_base}/report/{analyze_job_id}", wait_until="commit", timeout=30_000)
            _wait_until(page.get_by_role("heading", name="Report Insights"))
            report_search = page.get_by_placeholder("Filter report rows")
            report_search.fill(unique_name)
            _wait_until(page.get_by_text(f"q={unique_name}"), timeout_s=WAIT_TIMEOUT_S)
            page.get_by_role("button", name="Clear filters").click()
            _wait_for_input_value(report_search, "", timeout_s=WAIT_TIMEOUT_S)
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

            _heartbeat("open rollback page for executed apply job")
            page.goto(f"{browser_ui_base}/rollback/{apply_job_id}", wait_until="commit", timeout=30_000)
            _wait_until(page.get_by_role("heading", name="Rollback Recovery"))
            _wait_for_input_value(page.locator("#rollback-manifest"), rollback_manifest_path, timeout_s=WAIT_TIMEOUT_S)
            page.locator("#rollback-audit-reason").fill("live e2e rollback verification")
            page.get_by_role("button", name="Preview Rollback").click()

            _wait_for_job(
                api_base,
                lambda item: (
                    item.get("kind") == "rollback"
                    and item.get("status") == "succeeded"
                    and bool((item.get("summary") or {}).get("dry_run"))
                    and str((item.get("summary") or {}).get("manifest_path") or "").strip() == rollback_manifest_path
                ),
                label="rollback dry-run succeeded",
            )

            ack_checkbox = page.get_by_label(
                "I understand the rollback scope, and I confirm the current safety boundary before continuing."
            )
            rollback_execute_button = page.get_by_role("button", name="Roll Back Files")
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
                    and str((item.get("summary") or {}).get("manifest_path") or "").strip() == rollback_manifest_path
                ),
                label="rollback execute succeeded",
            )
            assert str(rollback_execute["id"]).startswith("job_")

            if source_path:
                _wait_for_path_state(Path(source_path), exists=True, timeout_s=WAIT_TIMEOUT_S)
            if target_path:
                _wait_for_path_state(Path(target_path), exists=False, timeout_s=WAIT_TIMEOUT_S)
                live_cleanup_actions.append(("cleanup_target_file", lambda: Path(target_path).unlink(missing_ok=True)))

            context.close()
            browser.close()
