import time
import types

import pytest

from packages.infrastructure import gemini_client


def test_parse_json_strict_empty_raises():
    with pytest.raises(ValueError):
        gemini_client.parse_json_strict("")


def test_call_gemini_parses_text(monkeypatch):
    class DummyResp:
        text = '{"x": 1}'

    class DummyModels:
        def generate_content(self, model, contents, config=None):
            return DummyResp()

    class DummyClient:
        models = DummyModels()

    class DummyTypes:
        class GenerateContentConfig:
            def __init__(self, temperature=0.0, response_mime_type=None):
                self.temperature = temperature
                self.response_mime_type = response_mime_type

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", lambda: (None, DummyTypes))

    out = gemini_client.call_gemini(DummyClient(), model="m", image_part=object(), prompt="p")
    assert out["x"] == 1


def test_call_gemini_parses_candidates(monkeypatch):
    class DummyPart:
        def __init__(self, text):
            self.text = text

    class DummyCandidate:
        def __init__(self):
            self.content = types.SimpleNamespace(parts=[DummyPart("{"), DummyPart('"y":2}')])

    class DummyResp:
        text = None
        candidates = [DummyCandidate()]

    class DummyModels:
        def generate_content(self, model, contents, config=None):
            return DummyResp()

    class DummyClient:
        models = DummyModels()

    class DummyTypes:
        class GenerateContentConfig:
            def __init__(self, temperature=0.0, response_mime_type=None):
                self.temperature = temperature
                self.response_mime_type = response_mime_type

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", lambda: (None, DummyTypes))

    out = gemini_client.call_gemini(DummyClient(), model="m", image_part=object(), prompt="p")
    assert out["y"] == 2


def test_call_gemini_text_raises_on_empty_response(monkeypatch):
    class DummyResp:
        text = ""
        candidates = []

    class DummyModels:
        def generate_content(self, model, contents, config=None):
            return DummyResp()

    class DummyClient:
        models = DummyModels()

    class DummyTypes:
        class GenerateContentConfig:
            def __init__(self, temperature=0.0, response_mime_type=None):
                self.temperature = temperature
                self.response_mime_type = response_mime_type

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", lambda: (None, DummyTypes))

    with pytest.raises(gemini_client.NonRetryableAIError, match="empty response"):
        gemini_client.call_gemini_text(DummyClient(), model="m", prompt="p")


def test_call_gemini_with_retry_success_after_fail(monkeypatch):
    calls = {"n": 0}

    def fake_call(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("boom")
        return {"ok": True}

    monkeypatch.setattr(gemini_client, "call_gemini", fake_call)
    out, attempts = gemini_client.call_gemini_with_retry(
        client=object(),
        model="m",
        image_part=object(),
        prompt="p",
        max_retries=2,
        retry_base_s=0.0,
        retry_max_s=0.0,
    )
    assert out["ok"] is True
    assert attempts == 1


def test_call_gemini_with_retry_raises(monkeypatch):
    def fake_call(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(gemini_client, "call_gemini", fake_call)
    with pytest.raises(RuntimeError):
        gemini_client.call_gemini_with_retry(
            client=object(),
            model="m",
            image_part=object(),
            prompt="p",
            max_retries=0,
            retry_base_s=0.0,
            retry_max_s=0.0,
        )


def test_call_gemini_with_retry_non_retryable(monkeypatch):
    calls = {"n": 0}

    def fake_call(*args, **kwargs):
        calls["n"] += 1
        raise gemini_client.NonRetryableAIError("bad json")

    monkeypatch.setattr(gemini_client, "call_gemini", fake_call)
    with pytest.raises(gemini_client.NonRetryableAIError):
        gemini_client.call_gemini_with_retry(
            client=object(),
            model="m",
            image_part=object(),
            prompt="p",
            max_retries=3,
            retry_base_s=0.0,
            retry_max_s=0.0,
        )
    assert calls["n"] == 1


def test_call_gemini_text_with_retry(monkeypatch):
    calls = {"n": 0}

    def fake_call(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("boom")
        return {"text": "ok"}

    monkeypatch.setattr(gemini_client, "call_gemini_text", fake_call)
    out, attempts = gemini_client.call_gemini_text_with_retry(
        client=object(),
        model="m",
        prompt="p",
        max_retries=2,
        retry_base_s=0.0,
        retry_max_s=0.0,
    )
    assert out["text"] == "ok"
    assert attempts == 1


def test_build_config_fallback():
    class DummyTypes:
        class GenerateContentConfig:
            def __init__(self, temperature=0.0, response_mime_type=None):
                if response_mime_type is not None:
                    raise RuntimeError("no mime type support")

    config = gemini_client.build_config(DummyTypes)
    assert config is not None


def test_run_with_timeout_returns_quickly_on_timeout():
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        gemini_client._run_with_timeout(lambda: time.sleep(0.2), 0.01)
    elapsed = time.monotonic() - started
    assert elapsed < 0.15


def test_invoke_with_timeout_hints_prefers_direct_timeout_kwargs():
    received = {}

    def fn(**kwargs):
        received.update(kwargs)
        return "ok"

    out = gemini_client._invoke_with_timeout_hints(fn, {"x": 1}, 2.0)
    assert out == "ok"
    assert received["x"] == 1
    assert received["timeout"] == 2.0


def test_invoke_with_timeout_hints_falls_back_to_run_with_timeout(monkeypatch):
    called = {"fallback": False}

    def fn(x):
        return x

    def fake_run(timeout_fn, timeout_s):
        called["fallback"] = True
        assert timeout_s == 3.0
        return timeout_fn()

    monkeypatch.setattr(gemini_client, "_run_with_timeout", fake_run)
    out = gemini_client._invoke_with_timeout_hints(fn, {"x": 7}, 3.0)
    assert out == 7
    assert called["fallback"] is True


def test_run_with_timeout_isolated_calls_avoid_cascading_timeouts():
    gemini_client._shutdown_timeout_executor()
    for _ in range(4):
        with pytest.raises(TimeoutError):
            gemini_client._run_with_timeout(lambda: time.sleep(2.0), 0.01)

    assert gemini_client._run_with_timeout(lambda: "ok", 0.5) == "ok"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (408, True),
        (429, True),
        (500, True),
        (400, False),
    ],
)
def test_is_retryable_exception_http_status_codes(status_code, expected):
    exc = RuntimeError("http error")
    exc.status_code = status_code  # type: ignore[attr-defined]
    assert gemini_client.is_retryable_exception(exc) is expected
