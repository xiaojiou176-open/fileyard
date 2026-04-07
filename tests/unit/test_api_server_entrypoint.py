from __future__ import annotations

import runpy
import sys
import types

from apps.api import server


def test_parse_args_uses_env_defaults(monkeypatch) -> None:
    monkeypatch.setenv("MOVI_WEB_API_HOST", "0.0.0.0")
    monkeypatch.setenv("MOVI_WEB_API_PORT", "19090")

    args = server.parse_args([])

    assert args.host == "0.0.0.0"
    assert args.port == 19090
    assert args.log_level == "info"
    assert args.reload is False


def test_parse_args_prefers_cli_args_over_env(monkeypatch) -> None:
    monkeypatch.setenv("MOVI_WEB_API_HOST", "127.0.0.5")
    monkeypatch.setenv("MOVI_WEB_API_PORT", "19555")

    args = server.parse_args(["--host", "127.0.0.1", "--port", "18081", "--log-level", "warning", "--reload"])

    assert args.host == "127.0.0.1"
    assert args.port == 18081
    assert args.log_level == "warning"
    assert args.reload is True


def test_main_invokes_uvicorn_with_parsed_args(monkeypatch) -> None:
    called: dict[str, object] = {}

    def fake_run(app: str, host: str, port: int, reload: bool, log_level: str) -> None:
        called.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
                "log_level": log_level,
            }
        )

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_run))

    server.main(["--host", "127.0.0.9", "--port", "19191", "--log-level", "debug", "--reload"])

    assert called == {
        "app": "apps.api.web_api:app",
        "host": "127.0.0.9",
        "port": 19191,
        "reload": True,
        "log_level": "debug",
    }


def test_module_main_branch_uses_env_defaults(monkeypatch) -> None:
    called: dict[str, object] = {}

    def fake_run(app: str, host: str, port: int, reload: bool, log_level: str) -> None:
        called.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
                "log_level": log_level,
            }
        )

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_run))
    monkeypatch.setenv("MOVI_WEB_API_HOST", "127.0.0.3")
    monkeypatch.setenv("MOVI_WEB_API_PORT", "18123")
    monkeypatch.setattr(sys, "argv", ["movi-web-api"])

    runpy.run_module("apps.api.server", run_name="__main__")

    assert called["app"] == "apps.api.web_api:app"
    assert called["host"] == "127.0.0.3"
    assert called["port"] == 18123
    assert called["reload"] is False
    assert called["log_level"] == "info"
