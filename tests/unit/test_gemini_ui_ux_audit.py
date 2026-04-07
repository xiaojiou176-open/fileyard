from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _ui_audit_dir(repo_root: Path, name: str) -> Path:
    return repo_root / ".runtime-cache" / "test" / "ui-audit" / name


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tooling" / "scripts" / "gemini_ui_ux_audit.py"
    spec = importlib.util.spec_from_file_location("gemini_ui_ux_audit", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod, repo_root


def test_validate_schema_normalizes_issues() -> None:
    mod, _ = _load_module()
    payload = {
        "passed": False,
        "summary": "s",
        "issues": [
            {
                "file": "a.tsx",
                "line": "12",
                "severity": "error",
                "category": "a11y",
                "rule_id": "wcag-2.4.11",
                "evidence_snippet": "button has outline: none and no replacement",
                "confidence": "0.8",
                "description": "d",
                "fix": "f",
            }
        ],
    }
    out = mod._validate_schema(payload)
    assert out["passed"] is False
    assert out["issues"][0]["line"] == 12
    assert out["issues"][0]["severity"] == "error"
    assert out["issues"][0]["rule_id"] == "wcag-2.4.11"
    assert out["issues"][0]["confidence"] == 0.8


def test_validate_schema_rejects_invalid_severity() -> None:
    mod, _ = _load_module()
    payload = {
        "issues": [
            {
                "file": "a.tsx",
                "line": 2,
                "severity": "critical",
                "category": "a11y",
                "rule_id": "wcag-2.5.8",
                "evidence_snippet": "target too small",
                "confidence": 0.5,
                "description": "bad severity",
                "fix": "fix",
            }
        ]
    }
    with pytest.raises(ValueError, match="invalid severity"):
        mod._validate_schema(payload)


def test_validate_schema_rejects_missing_structured_evidence() -> None:
    mod, _ = _load_module()
    payload = {
        "issues": [
            {
                "file": "a.tsx",
                "line": 10,
                "severity": "warning",
                "category": "ux",
                "confidence": 0.4,
                "description": "missing evidence fields",
                "fix": "add fields",
            }
        ]
    }
    with pytest.raises(ValueError, match="rule_id must be non-empty"):
        mod._validate_schema(payload)


def test_validate_schema_rejects_invalid_line_category_and_confidence() -> None:
    mod, _ = _load_module()
    payload = {
        "issues": [
            {
                "file": "a.tsx",
                "line": 0,
                "severity": "warning",
                "category": "custom",
                "rule_id": "custom-rule",
                "evidence_snippet": "x",
                "confidence": 1.2,
                "description": "invalid fields",
                "fix": "fix",
            }
        ]
    }
    with pytest.raises(ValueError, match="invalid category"):
        mod._validate_schema(payload)


def test_full_snapshot_contains_file_headers(tmp_path: Path) -> None:
    mod, repo_root = _load_module()
    target_dir = _ui_audit_dir(repo_root, "snapshot")
    target_dir.mkdir(parents=True, exist_ok=True)
    f = target_dir / "a.html"
    f.write_text("<html lang='en'></html>", encoding="utf-8")
    try:
        snap = mod._full_snapshot(repo_root, [f])
        assert "### FILE:" in snap
        assert "<html" in snap
    finally:
        f.unlink(missing_ok=True)


def test_iter_file_batches_splits_without_dropping_items() -> None:
    mod, _ = _load_module()
    file_paths = [Path(f"/tmp/file-{idx}.tsx") for idx in range(7)]
    batches = mod._iter_file_batches(file_paths, 3)
    assert len(batches) == 3
    assert [len(batch) for batch in batches] == [3, 3, 1]
    flattened = [item for batch in batches for item in batch]
    assert flattened == file_paths


def test_build_genai_client_sets_http_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    mod, _ = _load_module()
    captured: dict[str, object] = {}

    class _FakeHttpOptions:
        def __init__(self, *, timeout: int | None = None, **_kwargs: object) -> None:
            captured["timeout"] = timeout

    class _FakeTypes:
        HttpOptions = _FakeHttpOptions

    class _FakeGenai:
        class Client:
            def __init__(self, *, api_key: str, http_options: object | None = None) -> None:
                captured["api_key"] = api_key
                captured["http_options"] = http_options

    monkeypatch.setitem(sys.modules, "google", type("_GooglePkg", (), {"genai": _FakeGenai})())
    monkeypatch.setitem(sys.modules, "google.genai", type("_GoogleGenaiPkg", (), {"types": _FakeTypes})())

    client, types_module = mod._build_genai_client("test-key", timeout_ms=1234)
    assert captured["api_key"] == "test-key"
    assert captured["timeout"] == 1234
    assert client is not None
    assert types_module is _FakeTypes


def test_aggregate_batch_results_merges_passed_summary_and_issues() -> None:
    mod, _ = _load_module()
    merged = mod._aggregate_batch_results(
        [
            {"passed": True, "summary": "batch-1", "issues": [{"severity": "warning", "file": "a.tsx", "line": 1}]},
            {"passed": False, "summary": "batch-2", "issues": [{"severity": "error", "file": "b.tsx", "line": 2}]},
        ]
    )
    assert merged["passed"] is False
    assert "batch-1" in merged["summary"]
    assert "batch-2" in merged["summary"]
    assert len(merged["issues"]) == 2


def test_aggregate_batch_results_warning_only_stays_non_blocking() -> None:
    mod, _ = _load_module()
    merged = mod._aggregate_batch_results(
        [
            {"passed": False, "summary": "warning-only", "issues": [{"severity": "warning", "file": "a.tsx", "line": 1}]},
        ]
    )
    assert merged["passed"] is True
    assert merged["issues"][0]["severity"] == "warning"


def test_main_blocks_when_error_issue_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    mod, repo_root = _load_module()
    frontend_file = _ui_audit_dir(repo_root, "main-block") / "app.tsx"
    frontend_file.parent.mkdir(parents=True, exist_ok=True)
    frontend_file.write_text("export const App = () => <button>Hi</button>;\n", encoding="utf-8")

    class _FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

    class _FakeModels:
        def generate_content(self, *, model: str, contents: str, config: object | None = None) -> _FakeResponse:  # noqa: ARG002
            payload = {
                "passed": False,
                "summary": "found blocking issue",
                "issues": [
                    {
                        "file": str(frontend_file.relative_to(repo_root)),
                        "line": 1,
                        "severity": "error",
                        "category": "a11y",
                        "rule_id": "wcag-2.4.11",
                        "evidence_snippet": "button has no explicit focus style",
                        "confidence": 0.96,
                        "description": "focus visibility risk",
                        "fix": "add :focus-visible style",
                    }
                ],
            }
            return _FakeResponse(json.dumps(payload))

    class _FakeClient:
        def __init__(self) -> None:
            self.models = _FakeModels()

    monkeypatch.setattr(mod, "_candidate_files", lambda *_args, **_kwargs: [frontend_file])
    monkeypatch.setattr(mod, "_resolve_api_key", lambda *_args, **_kwargs: "test-key")

    class _FakeTypes:
        @staticmethod
        def GenerateContentConfig(**kwargs):
            return kwargs

    monkeypatch.setattr(mod, "_build_genai_client", lambda *_args, **_kwargs: (_FakeClient(), _FakeTypes()))
    monkeypatch.setattr(mod, "_staged_diff", lambda *_args, **_kwargs: "diff")
    monkeypatch.setattr(sys, "argv", ["gemini_ui_ux_audit.py", "--max-attempts", "1"])

    try:
        assert mod.main() == 1
    finally:
        frontend_file.unlink(missing_ok=True)


def test_main_passes_with_warning_only(monkeypatch: pytest.MonkeyPatch) -> None:
    mod, repo_root = _load_module()
    frontend_file = _ui_audit_dir(repo_root, "main-pass") / "app.tsx"
    frontend_file.parent.mkdir(parents=True, exist_ok=True)
    frontend_file.write_text("export const App = () => <div />;\n", encoding="utf-8")

    class _FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

    class _FakeModels:
        def generate_content(self, *, model: str, contents: str, config: object | None = None) -> _FakeResponse:  # noqa: ARG002
            payload = {
                "passed": True,
                "summary": "warning only",
                "issues": [
                    {
                        "file": str(frontend_file.relative_to(repo_root)),
                        "line": 1,
                        "severity": "warning",
                        "category": "maintainability",
                        "rule_id": "design-token-hardcode",
                        "evidence_snippet": "hardcoded spacing class may diverge from tokens",
                        "confidence": 0.75,
                        "description": "prefer spacing tokens",
                        "fix": "replace literal spacing with token var",
                    }
                ],
            }
            return _FakeResponse(json.dumps(payload))

    class _FakeClient:
        def __init__(self) -> None:
            self.models = _FakeModels()

    monkeypatch.setattr(mod, "_candidate_files", lambda *_args, **_kwargs: [frontend_file])
    monkeypatch.setattr(mod, "_resolve_api_key", lambda *_args, **_kwargs: "test-key")

    class _FakeTypes:
        @staticmethod
        def GenerateContentConfig(**kwargs):
            return kwargs

    monkeypatch.setattr(mod, "_build_genai_client", lambda *_args, **_kwargs: (_FakeClient(), _FakeTypes()))
    monkeypatch.setattr(mod, "_staged_diff", lambda *_args, **_kwargs: "diff")
    monkeypatch.setattr(sys, "argv", ["gemini_ui_ux_audit.py", "--max-attempts", "1"])

    try:
        assert mod.main() == 0
    finally:
        frontend_file.unlink(missing_ok=True)


def test_main_passes_when_model_marks_warning_only_batch_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    mod, repo_root = _load_module()
    frontend_file = _ui_audit_dir(repo_root, "main-warning-false") / "app.tsx"
    frontend_file.parent.mkdir(parents=True, exist_ok=True)
    frontend_file.write_text("export const App = () => <div />;\n", encoding="utf-8")

    class _FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

    class _FakeModels:
        def generate_content(self, *, model: str, contents: str, config: object | None = None) -> _FakeResponse:  # noqa: ARG002
            payload = {
                "passed": False,
                "summary": "warning only but model said failed",
                "issues": [
                    {
                        "file": str(frontend_file.relative_to(repo_root)),
                        "line": 1,
                        "severity": "warning",
                        "category": "maintainability",
                        "rule_id": "dry-violation",
                        "evidence_snippet": "duplicate helper can be extracted",
                        "confidence": 0.72,
                        "description": "prefer shared helper",
                        "fix": "extract common helper",
                    }
                ],
            }
            return _FakeResponse(json.dumps(payload))

    class _FakeClient:
        def __init__(self) -> None:
            self.models = _FakeModels()

    monkeypatch.setattr(mod, "_candidate_files", lambda *_args, **_kwargs: [frontend_file])
    monkeypatch.setattr(mod, "_resolve_api_key", lambda *_args, **_kwargs: "test-key")

    class _FakeTypes:
        @staticmethod
        def GenerateContentConfig(**kwargs):
            return kwargs

        @staticmethod
        def HttpOptions(**kwargs):
            return kwargs

    monkeypatch.setattr(mod, "_build_genai_client", lambda *_args, **_kwargs: (_FakeClient(), _FakeTypes()))
    monkeypatch.setattr(mod, "_staged_diff", lambda *_args, **_kwargs: "diff")
    monkeypatch.setattr(sys, "argv", ["gemini_ui_ux_audit.py", "--max-attempts", "1"])

    try:
        assert mod.main() == 0
    finally:
        frontend_file.unlink(missing_ok=True)
