# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import inspect
import json
import logging
import os
import re
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict

# -----------------------------
# Structured logging
# -----------------------------

_CONFIG_CONTEXT_DEFAULTS: Dict[str, str] = {}
APP_NAME = "fileyard"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        payload: Dict[str, Any] = {"timestamp": ts.replace("+00:00", "Z"), "level": record.levelname}
        payload["message"] = record.getMessage()
        event = getattr(record, "event", "")
        fields = getattr(record, "fields", None)
        if event:
            payload["event"] = event
        if isinstance(fields, dict) and fields:
            for key in (
                "run_id",
                "gate_run_id",
                "gate_name",
                "trace_id",
                "span_id",
                "module",
                "service",
                "component",
                "action",
                "status",
                "duration_ms",
                "failure_domain",
                "workspace_id",
                "upstream_id",
                "user_id",
                "session_id",
                "request_id",
                "manifest_id",
                "target_path",
            ):
                if key in fields:
                    payload[key] = fields[key]
            error_payload = _error_payload_from_fields(fields)
            if error_payload:
                payload["error"] = error_payload
            payload["fields"] = fields
        return json.dumps(payload, ensure_ascii=False)


def setup_logger(level: str, json_mode: bool) -> logging.Logger:
    logger = logging.getLogger("fileyard")
    for existing_handler in list(logger.handlers):
        logger.removeHandler(existing_handler)
        try:
            existing_handler.close()
        except Exception:
            pass
    logger.propagate = False
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    logger.setLevel(numeric)

    handler = logging.StreamHandler(sys.stdout)
    if json_mode:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)

    run_events_path = str(os.getenv("MOVI_RUN_EVENTS_PATH", "")).strip()
    if run_events_path:
        events_path = Path(run_events_path)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(events_path, encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)
    return logger


def _is_json_logger(logger: logging.Logger) -> bool:
    if not logger.handlers:
        return False
    return isinstance(logger.handlers[0].formatter, JsonFormatter)


def _format_fields(fields: Dict[str, Any]) -> str:
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return " ".join(parts)


_PATH_KEY_PATTERN = re.compile(r"(?:^|_)(?:path|manifest|output|input)(?:$|_)")
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:^|_)(?:token|secret|password|passwd|pwd|api[_-]?key|access[_-]?key|private[_-]?key|credential|auth)(?:$|_)"
)
_WIN_ABS_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
_UNIX_PATH_TOKEN_PATTERN = re.compile(r"(?<!\w)(/[^\s|]+)")
_SENSITIVE_MESSAGE_PATTERNS = (
    (
        re.compile(r'(?i)"authorization"\s*:\s*"bearer\s+[^"]+"'),
        lambda _: '"authorization":"Bearer ***"',
    ),
    (
        re.compile(r'(?i)"(token|secret|password|passwd|pwd|api[_-]?key|access[_-]?key|private[_-]?key|credential)"\s*:\s*"[^"]*"'),
        lambda m: f'"{m.group(1)}":"***"',
    ),
    (
        re.compile(r"(?i)\b(authorization)\s*[:=]\s*bearer\s+([^\s,;|]+)"),
        lambda m: f"{m.group(1)}=Bearer ***",
    ),
    (
        re.compile(
            r"(?i)\b(token|secret|password|passwd|pwd|api[_-]?key|access[_-]?key|private[_-]?key|credential)\b\s*[:=]\s*([^\s,;|]+)"
        ),
        lambda m: f"{m.group(1)}=***",
    ),
)


def _error_payload_from_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    mapping = {
        "error_type": "type",
        "error_code": "code",
        "error_message": "message",
        "error_stack": "stack",
        "error_retryable": "retryable",
        "error_cause": "cause",
    }
    payload: Dict[str, Any] = {}
    for source_key, target_key in mapping.items():
        if source_key not in fields:
            continue
        payload[target_key] = fields[source_key]
    return payload


def _mask_path(value: str) -> str:
    raw = str(value)
    normalized = raw.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts:
        return "***"
    tail = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    return f".../{tail}"


def _looks_like_path(value: str) -> bool:
    text = str(value)
    return text.startswith("/") or text.startswith("~/") or bool(_WIN_ABS_PATH_PATTERN.match(text))


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY_PATTERN.search(key.lower()))


def _sanitize_value(key: str, value: Any, redact_paths: bool) -> Any:
    if _is_sensitive_key(key):
        return "***"
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, str) and redact_paths:
            key_lower = key.lower()
            if _PATH_KEY_PATTERN.search(key_lower) or _looks_like_path(value):
                return _mask_path(value)
        return value
    if isinstance(value, dict):
        return {k: _sanitize_value(str(k), v, redact_paths) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(key, item, redact_paths) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(key, item, redact_paths) for item in value)
    return str(value)


def _sanitize_fields(fields: Dict[str, Any], redact_paths: bool) -> Dict[str, Any]:
    return {key: _sanitize_value(str(key), value, redact_paths) for key, value in fields.items()}


def _sanitize_message(message: str, redact_paths: bool) -> str:
    if not message:
        return message
    sanitized = message
    for pattern, repl in _SENSITIVE_MESSAGE_PATTERNS:
        sanitized = pattern.sub(repl, sanitized)
    if not redact_paths:
        return sanitized
    sanitized = _UNIX_PATH_TOKEN_PATTERN.sub(lambda m: _mask_path(m.group(1)), sanitized)
    tokens = sanitized.split()
    out: list[str] = []
    for token in tokens:
        if _looks_like_path(token):
            out.append(_mask_path(token))
        else:
            out.append(token)
    return " ".join(out)


def _infer_status_from_event(event: str) -> str:
    lower = str(event).lower()
    if lower.endswith(".start") or lower.endswith("_start"):
        return "start"
    if lower.endswith(".success") or lower.endswith("_success") or lower.endswith(".ok"):
        return "success"
    if lower.endswith(".retry") or lower.endswith("_retry"):
        return "retry"
    if lower.endswith(".skip") or lower.endswith("_skip"):
        return "skipped"
    if lower.endswith(".fail") or lower.endswith("_fail") or "error" in lower or "exception" in lower:
        return "fail"
    return "success"


def _infer_action_from_event(event: str, status: str) -> str:
    text = str(event).strip()
    if not text:
        return "unknown"
    lower = text.lower()
    suffixes = (f".{status}", f"_{status}", ".ok")
    for suffix in suffixes:
        if lower.endswith(suffix):
            return text[: len(text) - len(suffix)] or text
    return text


def _caller_module_name() -> str:
    frame = inspect.currentframe()
    try:
        current = frame
        for _ in range(3):
            if current is None:
                break
            current = current.f_back
        if current is None:
            return "packages.observability.unknown"
        name = str(current.f_globals.get("__name__", "") or "")
        return name or "packages.observability.unknown"
    finally:
        del frame


def _default_trace_id() -> str:
    return f"trc_{uuid.uuid4().hex[:12]}"


def _default_span_id() -> str:
    return f"spn_{uuid.uuid4().hex[:12]}"


def _env_default(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value if value else None


def _config_default(name: str) -> str | None:
    value = str(_CONFIG_CONTEXT_DEFAULTS.get(name, "") or "").strip()
    return value if value else None


def _workspace_id_from_root(raw_root: str | None) -> str | None:
    if not raw_root:
        return None
    candidate = Path(str(raw_root).strip()).expanduser()
    name = candidate.name.strip()
    return name or None


def set_log_context_defaults(**kwargs: Any) -> None:
    for key in ("trace_id", "request_id", "session_id", "user_id", "workspace_id", "service", "component"):
        raw = kwargs.get(key, "")
        text = str(raw or "").strip()
        if text:
            _CONFIG_CONTEXT_DEFAULTS[key] = text
        else:
            _CONFIG_CONTEXT_DEFAULTS.pop(key, None)


def _coerce_duration_ms(fields: Dict[str, Any]) -> Any:
    if "duration_ms" in fields:
        return fields["duration_ms"]
    duration_s = fields.get("duration_s")
    if isinstance(duration_s, (int, float)):
        return int(round(float(duration_s) * 1000))
    return None


def _resolve_exception(exc_info: Any, explicit_exception: Any) -> BaseException | None:
    if isinstance(explicit_exception, BaseException):
        return explicit_exception
    if isinstance(exc_info, BaseException):
        return exc_info
    if isinstance(exc_info, tuple) and len(exc_info) >= 2 and isinstance(exc_info[1], BaseException):
        return exc_info[1]
    return None


def _enrich_fields(
    event: str,
    level: int,
    message: str,
    fields: Dict[str, Any],
    *,
    exception: BaseException | None = None,
) -> Dict[str, Any]:
    enriched: Dict[str, Any] = dict(fields)

    status = str(enriched.get("status") or _infer_status_from_event(event))
    action = str(enriched.get("action") or _infer_action_from_event(event, status))
    cfg_trace_id = _config_default("trace_id")
    cfg_request_id = _config_default("request_id")
    cfg_session_id = _config_default("session_id")
    cfg_user_id = _config_default("user_id")
    cfg_workspace_id = _config_default("workspace_id")
    cfg_service = _config_default("service")
    cfg_component = _config_default("component")
    env_trace_id = _env_default("MOVI_TRACE_ID")
    env_request_id = _env_default("MOVI_REQUEST_ID")
    env_session_id = _env_default("MOVI_SESSION_ID")
    env_user_id = _env_default("MOVI_USER_ID")
    env_workspace_root = _env_default("MOVI_WORKSPACE_ROOT")
    trace_id = str(
        enriched.get("trace_id")
        or enriched.get("run_id")
        or enriched.get("request_id")
        or enriched.get("session_id")
        or env_trace_id
        or cfg_trace_id
        or _default_trace_id()
    )
    request_id = str(enriched.get("request_id") or env_request_id or cfg_request_id or trace_id)
    session_id = str(enriched.get("session_id") or env_session_id or cfg_session_id or trace_id)
    user_id = str(enriched.get("user_id") or env_user_id or cfg_user_id or "cli_anonymous")
    module = str(enriched.get("module") or _caller_module_name())
    span_id = str(enriched.get("span_id") or _default_span_id())
    workspace_id = str(enriched.get("workspace_id") or cfg_workspace_id or _workspace_id_from_root(env_workspace_root) or "default")
    service = str(enriched.get("service") or cfg_service or APP_NAME)
    component = str(enriched.get("component") or cfg_component or module.split(".")[-1])
    failure_domain = str(enriched.get("failure_domain") or "repo_logic")
    run_id = str(enriched.get("run_id") or trace_id)
    gate_run_id = str(enriched.get("gate_run_id") or "")
    gate_name = str(enriched.get("gate_name") or "")

    enriched["status"] = status
    enriched["action"] = action
    enriched["run_id"] = run_id
    enriched["trace_id"] = trace_id
    enriched["span_id"] = span_id
    enriched["request_id"] = request_id
    enriched["session_id"] = session_id
    enriched["user_id"] = user_id
    enriched["module"] = module
    enriched["service"] = service
    enriched["component"] = component
    enriched["workspace_id"] = workspace_id
    enriched["failure_domain"] = failure_domain
    if gate_run_id:
        enriched["gate_run_id"] = gate_run_id
    if gate_name:
        enriched["gate_name"] = gate_name

    duration_ms = _coerce_duration_ms(enriched)
    if duration_ms is not None:
        enriched["duration_ms"] = duration_ms

    if level >= logging.ERROR:
        if exception is not None:
            enriched.setdefault("error_type", type(exception).__name__)
            enriched.setdefault("error_code", "UNKNOWN")
            enriched.setdefault("error_message", str(exception) or message or "unknown error")
            enriched.setdefault("error_retryable", False)
            cause = exception.__cause__
            enriched.setdefault("error_cause", type(cause).__name__ if cause else "unknown")
            enriched.setdefault(
                "error_stack",
                "".join(traceback.format_exception(type(exception), exception, exception.__traceback__)).strip(),
            )
        else:
            enriched.setdefault("error_type", "UnknownError")
            enriched.setdefault("error_code", "UNKNOWN")
            enriched.setdefault("error_message", message or "unknown error")
            enriched.setdefault("error_retryable", False)
            enriched.setdefault("error_cause", "unknown")
            enriched.setdefault("error_stack", "")

    return enriched


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    *,
    redact_paths: bool = True,
    **fields: Any,
) -> None:
    runtime_fields = dict(fields)
    exception = _resolve_exception(runtime_fields.pop("exc_info", None), runtime_fields.pop("exception", None))
    exc_alias = runtime_fields.pop("exc", None)
    if exception is None and isinstance(exc_alias, BaseException):
        exception = exc_alias
    msg = _sanitize_message(message, redact_paths=redact_paths)
    safe_fields = _sanitize_fields(
        _enrich_fields(event=event, level=level, message=msg, fields=runtime_fields, exception=exception),
        redact_paths=redact_paths,
    )
    if safe_fields and not _is_json_logger(logger):
        suffix = _format_fields(safe_fields)
        if suffix:
            msg = f"{msg} | {suffix}"
    logger.log(level, msg, extra={"event": event, "fields": safe_fields})
