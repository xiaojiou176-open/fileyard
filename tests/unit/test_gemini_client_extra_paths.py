import pytest

from packages.infrastructure import gemini_client


def test_build_config_returns_none():
    class DummyTypes:
        class GenerateContentConfig:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("nope")

    assert gemini_client.build_config(DummyTypes) is None


def test_safe_delete_file_ignores_errors():
    calls = []

    class DummyFiles:
        def delete(self, name: str):
            calls.append(name)
            raise RuntimeError("boom")

    class DummyClient:
        files = DummyFiles()

    gemini_client.safe_delete_file(DummyClient(), "files/1")
    assert calls == ["files/1"]


def test_call_gemini_text_raises_on_empty(monkeypatch):
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

    with pytest.raises(gemini_client.NonRetryableAIError):
        gemini_client.call_gemini_text(DummyClient(), model="m", prompt="p")
