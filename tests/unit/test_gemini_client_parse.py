from packages.infrastructure import gemini_client


def test_parse_json_strict_basic():
    out = gemini_client.parse_json_strict('{"a": 1}')
    assert out == {"a": 1}


def test_parse_json_strict_with_extra():
    raw = 'prefix {"a": 2} suffix'
    out = gemini_client.parse_json_strict(raw)
    assert out["a"] == 2


def test_safe_delete_file_calls_delete():
    class _Files:
        def __init__(self):
            self.called = None

        def delete(self, name: str):
            self.called = name

    class _Client:
        def __init__(self):
            self.files = _Files()

    client = _Client()
    gemini_client.safe_delete_file(client, "files/123")
    assert client.files.called == "files/123"
