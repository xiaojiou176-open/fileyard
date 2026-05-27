# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

# -----------------------------
# Config loader (TOML/YAML/JSON)
# -----------------------------


def _load_toml(text: str) -> Dict[str, Any]:
    try:
        import tomllib

        loader = tomllib
    except Exception:
        try:
            import tomli  # type: ignore
        except Exception as exc:  # pragma: no cover - python <3.11 且无 tomli
            raise RuntimeError(f"TOML parser unavailable: {exc}") from exc
        loader = tomli
    try:
        data = loader.loads(text)
    except Exception as exc:
        raise RuntimeError(f"TOML parse failed: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("TOML top-level value must be an object")
    return data


def _load_yaml(text: str) -> Dict[str, Any]:
    try:
        import yaml as yaml_mod  # type: ignore[import-untyped]
    except Exception as exc:
        raise RuntimeError(f"Missing PyYAML: {exc}") from exc
    safe_load = getattr(yaml_mod, "safe_load", None)
    if not callable(safe_load):
        raise RuntimeError("PyYAML.safe_load is required")
    data = safe_load(text) or {}
    if not isinstance(data, dict):
        raise RuntimeError("YAML top-level value must be an object")
    return data


def _load_json(text: str) -> Dict[str, Any]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RuntimeError("JSON top-level value must be an object")
    return data


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Config file does not exist: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to read config file: {exc}") from exc

    suffix = path.suffix.lower()
    if suffix == ".toml":
        return _load_toml(text)
    if suffix in {".yaml", ".yml"}:
        return _load_yaml(text)
    if suffix == ".json":
        return _load_json(text)
    raise RuntimeError("Only .toml/.yaml/.yml/.json config files are supported")


def get_config_value(config: Dict[str, Any], section: str, key: str, default: Any) -> Any:
    if not isinstance(config, dict):
        return default
    section_cfg = config.get(section)
    if section and isinstance(section_cfg, dict) and key in section_cfg:
        return section_cfg[key]
    global_raw = config.get("global")
    global_cfg = global_raw if isinstance(global_raw, dict) else {}
    if key in global_cfg:
        return global_cfg[key]
    return default


def validate_config(
    config: Dict[str, Any],
    allowed: Mapping[str, Iterable[str]],
    expected_types: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    strict_unknown: bool = False,
) -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    errors: List[str] = []
    if not isinstance(config, dict):
        errors.append("Config top-level value must be an object")
        return warnings, errors
    allowed_map = {section: set(keys) for section, keys in allowed.items()}
    expected_map = expected_types or {}

    def _describe_expected(spec: Any) -> str:
        if isinstance(spec, tuple):
            return " or ".join(_describe_expected(item) for item in spec)
        if isinstance(spec, type):
            return spec.__name__
        return getattr(spec, "__name__", "custom validator")

    def _matches(spec: Any, value: Any) -> bool:
        if isinstance(spec, tuple):
            return any(_matches(item, value) for item in spec)
        if isinstance(spec, type):
            if spec is bool:
                return isinstance(value, bool)
            if spec is int:
                return isinstance(value, int) and not isinstance(value, bool)
            if spec is float:
                return isinstance(value, (int, float)) and not isinstance(value, bool)
            return isinstance(value, spec)
        if callable(spec):
            try:
                return bool(spec(value))
            except Exception:
                return False
        return False

    for section, value in config.items():
        if section not in allowed_map:
            msg = f"Unknown config section: {section}"
            if strict_unknown:
                errors.append(msg)
            else:
                warnings.append(msg)
            continue
        if not isinstance(value, dict):
            errors.append(f"Config section must be an object: {section}")
            continue
        section_expected = expected_map.get(section, {})
        for key, raw in value.items():
            if key not in allowed_map[section]:
                msg = f"Unknown config key: {section}.{key}"
                if strict_unknown:
                    errors.append(msg)
                else:
                    warnings.append(msg)
                continue
            expected = section_expected.get(key)
            if expected is not None and not _matches(expected, raw):
                actual = type(raw).__name__
                expected_desc = _describe_expected(expected)
                errors.append(f"Invalid config value type: {section}.{key} (expected {expected_desc}, got {actual})")
    return warnings, errors
