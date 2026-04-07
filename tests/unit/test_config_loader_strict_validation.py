import sys
import types

from packages.infrastructure.config_loader import load_config, validate_config


def test_load_config_yaml_requires_safe_load(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("global: {}", encoding="utf-8")

    fake_yaml = types.ModuleType("yaml")
    monkeypatch.setitem(sys.modules, "yaml", fake_yaml)

    try:
        load_config(path)
        raised = False
    except RuntimeError as exc:
        raised = "safe_load" in str(exc)
    assert raised is True


def test_validate_config_strict_unknown_and_expected_types():
    def raising_validator(_value):
        raise RuntimeError("bad value")

    cfg = {
        "global": {
            "flag": True,
            "retries": False,
            "ratio": "x",
            "mode": [],
            "callable_key": "v",
            "extra": 1,
        },
        "unknown_group": {"x": 1},
    }
    allowed = {"global": {"flag", "retries", "ratio", "mode", "callable_key"}}
    expected = {
        "global": {
            "flag": bool,
            "retries": int,
            "ratio": float,
            "mode": (int, str),
            "callable_key": raising_validator,
        }
    }

    warnings, errors = validate_config(cfg, allowed, expected, strict_unknown=True)
    assert warnings == []
    assert "Unknown config section: unknown_group" in errors
    assert "Unknown config key: global.extra" in errors
    assert any("global.retries" in item and "expected int" in item for item in errors)
    assert any("global.ratio" in item and "expected float" in item for item in errors)
    assert any("global.mode" in item and "expected int or str" in item for item in errors)
    assert any("global.callable_key" in item and "expected raising_validator" in item for item in errors)


def test_validate_config_rejects_bool_for_int_and_float_expected_types():
    cfg = {"global": {"retries": True, "ratio": True}}
    allowed = {"global": {"retries", "ratio"}}
    expected = {"global": {"retries": int, "ratio": float}}

    _, errors = validate_config(cfg, allowed, expected, strict_unknown=True)

    assert any("global.retries" in item and "expected int" in item and "got bool" in item for item in errors)
    assert any("global.ratio" in item and "expected float" in item and "got bool" in item for item in errors)


def test_validate_config_callable_without_name_uses_custom_validator_label():
    class NoNameValidator:
        def __call__(self, _value):
            return False

    cfg = {"global": {"token": "abc"}}
    allowed = {"global": {"token"}}
    expected = {"global": {"token": NoNameValidator()}}

    _, errors = validate_config(cfg, allowed, expected, strict_unknown=True)

    assert any("global.token" in item and "expected custom validator" in item for item in errors)


def test_validate_config_tuple_expected_uses_any_semantics_with_callable_failure():
    def boom(_value):
        raise RuntimeError("validator boom")

    cfg = {"global": {"mode": "safe"}}
    allowed = {"global": {"mode"}}
    expected = {"global": {"mode": (boom, str)}}

    warnings, errors = validate_config(cfg, allowed, expected, strict_unknown=True)

    # Counterfactual: 若 tuple 匹配从 any 变成 all，或 callable 异常未被吞掉，此处会失败。
    assert warnings == []
    assert errors == []
