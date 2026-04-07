from __future__ import annotations

import runpy
import sys

import pytest

from apps.api import web_api_server


def test_web_api_server_main_uses_env(monkeypatch):
    called: dict[str, object] = {}

    def fake_run(app: str, host: str, port: int, reload: bool, log_level: str):
        called.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
                "log_level": log_level,
            }
        )

    monkeypatch.setenv("MOVI_WEB_API_HOST", "0.0.0.0")
    monkeypatch.setenv("MOVI_WEB_API_PORT", "19090")
    monkeypatch.setattr(web_api_server.uvicorn, "run", fake_run)

    web_api_server.main([])

    assert called == {
        "app": "apps.api.web_api:app",
        "host": "0.0.0.0",
        "port": 19090,
        "reload": False,
        "log_level": "info",
    }


def test_web_api_server_main_prefers_cli_args(monkeypatch):
    called: dict[str, object] = {}

    def fake_run(app: str, host: str, port: int, reload: bool, log_level: str):
        called.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
                "log_level": log_level,
            }
        )

    monkeypatch.setenv("MOVI_WEB_API_HOST", "127.0.0.5")
    monkeypatch.setenv("MOVI_WEB_API_PORT", "19555")
    monkeypatch.setattr(web_api_server.uvicorn, "run", fake_run)

    web_api_server.main(["--host", "0.0.0.0", "--port", "19091", "--log-level", "warning", "--reload"])

    assert called == {
        "app": "apps.api.web_api:app",
        "host": "0.0.0.0",
        "port": 19091,
        "reload": True,
        "log_level": "warning",
    }


def test_web_api_server_help_exits_cleanly_without_starting_server(monkeypatch, capsys):
    called = {"uvicorn_run": False}

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        called["uvicorn_run"] = True

    monkeypatch.setattr(web_api_server.uvicorn, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        web_api_server.main(["--help"])

    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert "usage:" in captured.out
    assert "--host" in captured.out
    assert called["uvicorn_run"] is False


def test_web_api_server_module_main_branch(monkeypatch):
    called: dict[str, object] = {}

    def fake_run(app: str, host: str, port: int, reload: bool, log_level: str):
        called["app"] = app
        called["host"] = host
        called["port"] = port
        called["reload"] = reload
        called["log_level"] = log_level

    monkeypatch.setattr(web_api_server.uvicorn, "run", fake_run)
    monkeypatch.setenv("MOVI_WEB_API_HOST", "127.0.0.9")
    monkeypatch.setenv("MOVI_WEB_API_PORT", "19191")
    monkeypatch.setattr(sys, "argv", ["movi-web-api"])
    sys.modules.pop("apps.api.web_api_server", None)

    runpy.run_module("apps.api.web_api_server", run_name="__main__")

    assert called["app"] == "apps.api.web_api:app"
    assert called["host"] == "127.0.0.9"
    assert called["port"] == 19191
