import os
import re
import sys
from pathlib import Path
from typing import Callable, Tuple

import pytest

from packages.infrastructure.gemini_client import build_client, call_gemini_text_with_retry

LIVE_FLAG = "FILEYARD_RUN_LIVE_TESTS"
LIVE_MAX_RETRIES = 2
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
_PLACEHOLDER_TOKEN_RE = re.compile(
    r"(^|[^a-z0-9])(dummy|test|mock|fake|placeholder|sample|changeme|replaceme)([^a-z0-9]|$)",
    re.IGNORECASE,
)


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


def _resolve_live_var_env_then_runtime_env(name: str, default: str = "") -> str:
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
    return _resolve_live_var_env_then_runtime_env(LIVE_FLAG, "0").strip() == "1"


@pytest.fixture(autouse=True)
def _restore_live_env_vars():
    keys = (LIVE_FLAG, "GEMINI_API_KEY", "GEMINI_MODEL")
    snapshot = {key: os.environ.get(key) for key in keys}
    yield
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _looks_like_placeholder_secret(value: str) -> bool:
    normalized = value.strip()
    if len(normalized) < 20:
        return True
    return bool(_PLACEHOLDER_TOKEN_RE.search(normalized))


def _live_llm_config() -> Tuple[str, str]:
    api_key = _resolve_live_var_env_then_runtime_env("GEMINI_API_KEY", "").strip()
    model = _resolve_live_var_env_then_runtime_env("GEMINI_MODEL", "").strip()
    if not api_key:
        pytest.fail("live_llm enabled but GEMINI_API_KEY is missing (checked workspace runtime env -> current env)")
    if not model:
        pytest.fail("live_llm enabled but GEMINI_MODEL is missing (checked workspace runtime env -> current env)")
    if _looks_like_placeholder_secret(api_key):
        pytest.fail(
            "live_llm preflight failed: GEMINI_API_KEY looks like a placeholder (dummy/test/mock/fake/sample/changeme or too short)"
        )
    if not _MODEL_RE.fullmatch(model):
        pytest.fail(f"live_llm preflight failed: GEMINI_MODEL has invalid format: {model!r}")
    if not model.lower().startswith("gemini-"):
        pytest.fail(f"live_llm preflight failed: GEMINI_MODEL must start with 'gemini-' (Gemini-only policy), got {model!r}")
    return api_key, model


def test_live_flag_prefers_env_over_dotenv(monkeypatch):
    monkeypatch.setenv(LIVE_FLAG, "1")
    monkeypatch.setattr(
        sys.modules[__name__],
        "_read_runtime_env_value",
        lambda name: "0" if name == LIVE_FLAG else "",
    )
    assert _is_live_enabled() is True


def test_live_llm_config_prefers_env_api_key_and_env_model(monkeypatch):
    dotenv_api_key = "placeholder_live_key_from_dotenv_1234567890"
    env_api_key = "real_live_key_from_env_abcdefghij"
    dotenv_model = "gemini-from-dotenv"
    env_model = "gemini-from-env"
    monkeypatch.setenv("GEMINI_API_KEY", env_api_key)
    monkeypatch.setenv("GEMINI_MODEL", env_model)
    monkeypatch.setattr(
        sys.modules[__name__],
        "_read_runtime_env_value",
        lambda name: dotenv_api_key if name == "GEMINI_API_KEY" else dotenv_model if name == "GEMINI_MODEL" else "",
    )

    api_key, model = _live_llm_config()
    assert api_key == env_api_key
    assert model == env_model


def _classify_live_llm_error(exc: BaseException) -> str:
    detail = f"{type(exc).__name__}: {exc}".lower()
    network_hints = (
        "timeout",
        "timed out",
        "unavailable",
        "connection",
        "dns",
        "econn",
        "503",
        "502",
        "504",
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
        pytest.fail("live_llm teardown failed: " + "; ".join(failures))


@pytest.mark.live_llm
def test_live_llm_env_preflight():
    # test-quality: allow-no-assert
    if not _is_live_enabled():
        pytest.skip(f"set {LIVE_FLAG}=1 to run live LLM tests")
    _live_llm_config()


@pytest.mark.live_llm
def test_live_llm_json_contract(live_cleanup_actions):
    if not _is_live_enabled():
        pytest.skip(f"set {LIVE_FLAG}=1 to run live LLM tests")

    api_key, model = _live_llm_config()

    # Read-only live policy: if a future live test writes externally, it must register teardown.
    assert not live_cleanup_actions

    client = build_client(api_key)
    prompt = (
        "请返回严格 JSON 对象，且仅包含这些字段: "
        "kind,category,title,tags,confidence,notes。"
        "要求: kind/category/title/notes 为字符串，tags 为字符串数组，"
        "confidence 为 0 到 1 的数字。"
    )

    try:
        payload, attempts = call_gemini_text_with_retry(
            client=client,
            model=model,
            prompt=prompt,
            max_retries=LIVE_MAX_RETRIES,
            retry_base_s=0.5,
            retry_max_s=2.0,
            timeout_s=60.0,
        )
    except Exception as exc:  # pragma: no cover - env-dependent branch
        category = _classify_live_llm_error(exc)
        pytest.fail(f"live_llm request failed for model={model!r} LIVE_ERROR_CLASS={category}: {type(exc).__name__}: {exc}")

    assert isinstance(payload, dict)
    required = {"kind", "category", "title", "tags", "confidence", "notes"}
    assert required.issubset(set(payload.keys()))
    assert all(key in required for key in payload.keys())
    assert isinstance(payload["kind"], str) and payload["kind"].strip()
    assert isinstance(payload["category"], str) and payload["category"].strip()
    assert isinstance(payload["title"], str)
    assert isinstance(payload["notes"], str)
    assert isinstance(payload["tags"], list)
    assert all(isinstance(tag, str) for tag in payload["tags"])

    confidence = payload["confidence"]
    assert isinstance(confidence, (int, float))
    assert 0.0 <= float(confidence) <= 1.0
    assert attempts >= 0
    assert attempts <= LIVE_MAX_RETRIES
