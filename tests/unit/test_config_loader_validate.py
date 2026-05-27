import builtins
import sys

import pytest

from packages.infrastructure.config_loader import load_config, validate_config


def test_validate_config_non_dict_top_level():
    warnings, errors = validate_config([], {"global": {"log_level"}})  # type: ignore[arg-type]
    assert warnings == []
    assert errors == ["Config top-level value must be an object"]


def test_validate_config_unknown_group_key_and_bad_section_type():
    cfg = {
        "global": {"log_level": "INFO", "extra": "x"},
        "apply": "bad",
        "unknown": {"x": 1},
    }
    allowed = {
        "global": {"log_level"},
        "apply": {"dedupe"},
    }

    warnings, errors = validate_config(cfg, allowed)

    assert "Unknown config key: global.extra" in warnings
    assert "Unknown config section: unknown" in warnings
    assert errors == ["Config section must be an object: apply"]


def test_load_config_toml_parse_error(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("invalid = [", encoding="utf-8")

    with pytest.raises(RuntimeError) as exc_info:
        load_config(path)
    assert "TOML parse failed" in str(exc_info.value)


def test_load_config_yaml_import_error(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("global: {}", encoding="utf-8")

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ModuleNotFoundError("yaml missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sys.modules.pop("yaml", None)

    with pytest.raises(RuntimeError) as exc_info:
        load_config(path)
    assert "Missing PyYAML" in str(exc_info.value)
