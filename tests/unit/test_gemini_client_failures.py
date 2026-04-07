import pytest

from packages.infrastructure import gemini_client


def test_build_client_missing_dependency(monkeypatch):
    def fake_lazy():
        raise RuntimeError("missing")

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", fake_lazy)
    with pytest.raises(RuntimeError):
        gemini_client.build_client("k")


def test_call_gemini_text_candidates(monkeypatch):
    class DummyPart:
        def __init__(self, text):
            self.text = text

    class DummyCandidate:
        def __init__(self):
            self.content = type("C", (), {"parts": [DummyPart("{"), DummyPart('"a":1}')]})()

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

    out = gemini_client.call_gemini_text(DummyClient(), model="m", prompt="p")
    assert out["a"] == 1


def test_call_gemini_raises(monkeypatch):
    class DummyModels:
        def generate_content(self, model, contents, config=None):
            raise RuntimeError("boom")

    class DummyClient:
        models = DummyModels()

    class DummyTypes:
        class GenerateContentConfig:
            def __init__(self, temperature=0.0, response_mime_type=None):
                self.temperature = temperature
                self.response_mime_type = response_mime_type

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", lambda: (None, DummyTypes))

    with pytest.raises(RuntimeError):
        gemini_client.call_gemini(DummyClient(), model="m", image_part=object(), prompt="p")


def test_parse_json_strict_no_object():
    with pytest.raises(ValueError):
        gemini_client.parse_json_strict("no json here")
