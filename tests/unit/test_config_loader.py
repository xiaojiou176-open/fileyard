import builtins
import sys
from pathlib import Path

import pytest

from packages.infrastructure.config_loader import get_config_value, load_config


def test_load_config_toml(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[global]
log_level = "INFO"
[analyze]
manifest = "out.jsonl"
""",
        encoding="utf-8",
    )
    data = load_config(path)
    assert data["global"]["log_level"] == "INFO"
    assert data["analyze"]["manifest"] == "out.jsonl"


def test_load_config_yaml(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        """
global:
  log_json: true
apply:
  dedupe: false
""",
        encoding="utf-8",
    )
    data = load_config(path)
    assert data["global"]["log_json"] is True
    assert data["apply"]["dedupe"] is False


def test_load_config_json(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text('{"global": {"run_id": "abc"}}', encoding="utf-8")
    data = load_config(path)
    assert data["global"]["run_id"] == "abc"


def test_get_config_value():
    cfg = {"global": {"log_level": "INFO"}, "apply": {"dedupe": False}}
    assert get_config_value(cfg, "apply", "dedupe", True) is False
    assert get_config_value(cfg, "apply", "log_level", "WARN") == "INFO"
    assert get_config_value(cfg, "missing", "x", 123) == 123


def test_load_config_missing(tmp_path: Path):
    with pytest.raises(RuntimeError):
        load_config(tmp_path / "missing.toml")


def test_load_config_yaml_non_dict(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        """
- a
- b
""",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        load_config(path)


def test_load_config_json_non_dict(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_config(path)


def test_load_config_toml_non_dict(monkeypatch, tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("a = 1", encoding="utf-8")

    class DummyToml:
        @staticmethod
        def loads(_):
            return ["bad"]

    monkeypatch.setitem(sys.modules, "tomllib", DummyToml)
    with pytest.raises(RuntimeError):
        load_config(path)


def test_load_config_toml_fallback_tomli(monkeypatch, tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[global]\nlog_level = "INFO"\n', encoding="utf-8")

    class DummyTomli:
        @staticmethod
        def loads(_):
            return {"global": {"log_level": "INFO"}}

    monkeypatch.setitem(sys.modules, "tomli", DummyTomli)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "tomllib":
            raise ModuleNotFoundError("tomllib missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    data = load_config(path)
    assert data["global"]["log_level"] == "INFO"


def test_load_config_unsupported_extension(tmp_path: Path):
    path = tmp_path / "config.txt"
    path.write_text("x=1", encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_config(path)


def test_load_config_read_fail(monkeypatch, tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")

    def _bad_read(*_args, **_kwargs):
        raise RuntimeError("read")

    monkeypatch.setattr(Path, "read_text", _bad_read)
    with pytest.raises(RuntimeError):
        load_config(path)


def test_get_config_value_non_dict():
    assert get_config_value("bad", "apply", "x", 7) == 7
