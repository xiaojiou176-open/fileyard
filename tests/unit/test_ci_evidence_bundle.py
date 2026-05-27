from __future__ import annotations

from pathlib import Path

from tooling.scripts.generate_ci_evidence_bundle import _redact_sensitive_payload, _resolve_runtime_root


def test_resolve_runtime_root_accepts_explicit_runtime_cache_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    runtime_root = repo_root / ".runtime-cache"
    runtime_root.mkdir(parents=True)

    assert _resolve_runtime_root(repo_root, runtime_root) == runtime_root


def test_resolve_runtime_root_promotes_logs_dir_to_runtime_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    runtime_root = repo_root / ".runtime-cache"
    logs_root = runtime_root / "logs"
    logs_root.mkdir(parents=True)

    assert _resolve_runtime_root(repo_root, logs_root) == runtime_root


def test_resolve_runtime_root_detects_embedded_runtime_cache_from_collected_artifacts(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    artifacts_root = repo_root / ".runtime-cache" / "ci" / "collected"
    embedded_runtime = artifacts_root / ".runtime-cache"
    embedded_runtime.mkdir(parents=True)

    assert _resolve_runtime_root(repo_root, artifacts_root) == embedded_runtime


def test_redact_sensitive_payload_masks_secret_like_keys() -> None:
    payload = {
        "api_key": "secret-value",
        "nested": {"token_value": "abc", "safe": "ok"},
        "items": [{"password": "pw"}, {"note": "ok"}],
    }

    redacted = _redact_sensitive_payload(payload)

    assert redacted["api_key"] == "<redacted>"
    assert redacted["nested"]["token_value"] == "<redacted>"
    assert redacted["nested"]["safe"] == "ok"
    assert redacted["items"][0]["password"] == "<redacted>"
    assert redacted["items"][1]["note"] == "ok"
