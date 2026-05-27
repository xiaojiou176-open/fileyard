# -*- coding: utf-8 -*-
from __future__ import annotations

import atexit
import json
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from packages.infrastructure.media_scanner import guess_mime
from packages.observability.logging_utils import log_event


class NonRetryableAIError(RuntimeError):
    """Error class for request/response failures that should not be retried."""


_TIMEOUT_EXECUTOR: ThreadPoolExecutor | None = None
_TIMEOUT_SEMAPHORE: threading.BoundedSemaphore | None = None
_TIMEOUT_EXECUTOR_LOCK = threading.Lock()
_TIMEOUT_EXECUTOR_WORKERS = 4


def _get_timeout_executor() -> ThreadPoolExecutor:
    global _TIMEOUT_EXECUTOR, _TIMEOUT_SEMAPHORE
    with _TIMEOUT_EXECUTOR_LOCK:
        if _TIMEOUT_EXECUTOR is None:
            _TIMEOUT_EXECUTOR = ThreadPoolExecutor(max_workers=_TIMEOUT_EXECUTOR_WORKERS, thread_name_prefix="gemini-timeout")
        if _TIMEOUT_SEMAPHORE is None:
            _TIMEOUT_SEMAPHORE = threading.BoundedSemaphore(_TIMEOUT_EXECUTOR_WORKERS)
        return _TIMEOUT_EXECUTOR


def _shutdown_timeout_executor() -> None:
    global _TIMEOUT_EXECUTOR, _TIMEOUT_SEMAPHORE
    with _TIMEOUT_EXECUTOR_LOCK:
        if _TIMEOUT_EXECUTOR is not None:
            _TIMEOUT_EXECUTOR.shutdown(wait=False, cancel_futures=True)
            _TIMEOUT_EXECUTOR = None
        _TIMEOUT_SEMAPHORE = None


atexit.register(_shutdown_timeout_executor)


def _run_with_timeout(func, timeout_s: float | None):
    if timeout_s is None or timeout_s <= 0:
        return func()
    start = time.monotonic()
    executor = _get_timeout_executor()
    with _TIMEOUT_EXECUTOR_LOCK:
        semaphore = _TIMEOUT_SEMAPHORE
    if semaphore is None:
        raise RuntimeError("timeout semaphore unavailable")
    if not semaphore.acquire(timeout=timeout_s):
        # Isolate future calls from potentially saturated workers after timeout.
        _shutdown_timeout_executor()
        raise TimeoutError(f"operation timed out after {timeout_s:.2f}s")
    elapsed = time.monotonic() - start
    remaining = timeout_s - elapsed
    if remaining <= 0:
        semaphore.release()
        _shutdown_timeout_executor()
        raise TimeoutError(f"operation timed out after {timeout_s:.2f}s")
    try:
        future = executor.submit(func)
    except Exception:
        semaphore.release()
        raise
    future.add_done_callback(lambda _done: semaphore.release())
    try:
        return future.result(timeout=remaining)
    except FutureTimeoutError as exc:
        future.cancel()
        _shutdown_timeout_executor()
        raise TimeoutError(f"operation timed out after {timeout_s:.2f}s") from exc


def _invoke_with_timeout_hints(func, kwargs: Dict[str, Any], timeout_s: float | None):
    if timeout_s is None or timeout_s <= 0:
        return func(**kwargs)

    timeout_hints = (
        {"timeout": timeout_s},
        {"request_timeout": timeout_s},
        {"timeout_seconds": timeout_s},
        {"request_options": {"timeout": timeout_s}},
    )
    for hint in timeout_hints:
        try:
            return func(**{**kwargs, **hint})
        except TypeError:
            continue
    return _run_with_timeout(lambda: func(**kwargs), timeout_s)


def _status_code_from_exc(exc: Exception) -> int | None:
    current: Exception | None = exc
    while current is not None:
        for attr in ("status_code", "code"):
            value = getattr(current, attr, None)
            if isinstance(value, int):
                return value
        response = getattr(current, "response", None)
        code = getattr(response, "status_code", None)
        if isinstance(code, int):
            return code
        cause = getattr(current, "__cause__", None)
        current = cause if isinstance(cause, Exception) else None
    return None


def is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (NonRetryableAIError, ValueError, TypeError, KeyError)):
        return False
    if isinstance(exc, TimeoutError):
        return True
    code = _status_code_from_exc(exc)
    if code is None:
        return True
    if code in {408, 409, 425, 429, 500, 502, 503, 504}:
        return True
    return False


def _lazy_import_gemini():
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except Exception as exc:  # pragma: no cover - import error path
        raise RuntimeError("Missing dependency: google-genai. Install it with `pip install google-genai`.") from exc
    return genai, types


def build_client(api_key: str):
    genai, _ = _lazy_import_gemini()
    return genai.Client(api_key=api_key)


def build_config(types_module, *, strict: bool = False):
    try:
        return types_module.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
        )
    except Exception as exc:
        if strict:
            raise RuntimeError(f"Gemini config error: failed to set response_mime_type: {exc}") from exc
        try:
            return types_module.GenerateContentConfig(temperature=0.0)
        except Exception as config_exc:
            if strict:
                raise RuntimeError(f"Gemini config error: failed to set temperature: {config_exc}") from config_exc
            return None


def _extract_first_json_object(raw: str) -> str:
    start = None
    depth = 0
    in_str = False
    escape = False
    for idx, ch in enumerate(raw):
        if ch == "\\" and in_str:
            escape = not escape
            continue
        if ch == '"' and not escape:
            in_str = not in_str
        escape = False
        if in_str:
            continue
        if ch == "{":
            if start is None:
                start = idx
            depth += 1
        elif ch == "}":
            if start is None:
                continue
            depth -= 1
            if depth == 0:
                return raw[start : idx + 1]
    raise ValueError("no json object found")


def parse_json_strict(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty response")
    try:
        return json.loads(raw)
    except Exception:
        snippet = _extract_first_json_object(raw)
        return json.loads(snippet)


def call_gemini(
    client,
    model: str,
    image_part,
    prompt: str,
    *,
    timeout_s: float | None = None,
) -> Dict[str, Any]:
    _, types = _lazy_import_gemini()

    config = build_config(types, strict=True)
    try:
        kwargs = {"model": model, "contents": [image_part, prompt]}
        if config is not None:
            kwargs["config"] = config
        resp = _invoke_with_timeout_hints(client.models.generate_content, kwargs, timeout_s)
    except TimeoutError as exc:
        raise RuntimeError(f"Gemini request timed out: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc

    text = getattr(resp, "text", None)
    if not text:
        try:
            parts = resp.candidates[0].content.parts  # type: ignore
            text = "".join(getattr(p, "text", "") for p in parts)
        except Exception:
            text = ""

    try:
        return parse_json_strict(text)
    except Exception as exc:
        raise NonRetryableAIError(f"Gemini returned unparsable content: {exc}") from exc


def call_gemini_with_retry(
    client,
    model: str,
    image_part,
    prompt: str,
    max_retries: int,
    retry_base_s: float,
    retry_max_s: float,
    *,
    timeout_s: float | None = None,
) -> Tuple[Dict[str, Any], int]:
    attempt = 0
    last_exc: Optional[Exception] = None
    while True:
        try:
            return (
                call_gemini(client, model=model, image_part=image_part, prompt=prompt, timeout_s=timeout_s),
                attempt,
            )
        except Exception as exc:
            last_exc = exc
            if not is_retryable_exception(exc):
                break
            if attempt >= max_retries:
                break
            sleep_s = max(0.0, min(retry_max_s, retry_base_s * (2**attempt)))
            time.sleep(random.uniform(0.0, sleep_s))
            attempt += 1
    if last_exc:
        raise last_exc
    raise RuntimeError("Gemini API call failed after retries")


def call_gemini_text(
    client,
    model: str,
    prompt: str,
    *,
    timeout_s: float | None = None,
) -> Dict[str, Any]:
    _, types = _lazy_import_gemini()
    config = build_config(types, strict=True)
    try:
        kwargs = {"model": model, "contents": [prompt]}
        if config is not None:
            kwargs["config"] = config
        resp = _invoke_with_timeout_hints(client.models.generate_content, kwargs, timeout_s)
    except TimeoutError as exc:
        raise RuntimeError(f"Gemini request timed out: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc

    text = getattr(resp, "text", None)
    if not text:
        try:
            parts = resp.candidates[0].content.parts  # type: ignore
            text = "".join(getattr(p, "text", "") for p in parts)
        except Exception:
            text = ""
    try:
        return parse_json_strict(text)
    except Exception as exc:
        raise NonRetryableAIError(f"Gemini returned unparsable content: {exc}") from exc


def call_gemini_text_with_retry(
    client,
    model: str,
    prompt: str,
    max_retries: int,
    retry_base_s: float,
    retry_max_s: float,
    *,
    timeout_s: float | None = None,
) -> Tuple[Dict[str, Any], int]:
    attempt = 0
    last_exc: Optional[Exception] = None
    while True:
        try:
            return call_gemini_text(client, model=model, prompt=prompt, timeout_s=timeout_s), attempt
        except Exception as exc:
            last_exc = exc
            if not is_retryable_exception(exc):
                break
            if attempt >= max_retries:
                break
            sleep_s = max(0.0, min(retry_max_s, retry_base_s * (2**attempt)))
            time.sleep(random.uniform(0.0, sleep_s))
            attempt += 1
    if last_exc:
        raise last_exc
    raise RuntimeError("Gemini API call failed after retries")


def safe_delete_file(client, name: str, logger: Optional[logging.Logger] = None, *, timeout_s: float | None = 60.0) -> bool:
    if not name:
        return True
    try:
        _invoke_with_timeout_hints(client.files.delete, {"name": name}, timeout_s)
        return True
    except Exception as exc:
        if logger:
            log_event(
                logger,
                logging.WARNING,
                "gemini_file_delete_fail",
                "Gemini file delete failed",
                name=name,
                error=str(exc),
            )
        return False


def build_file_part(
    path: Path,
    client,
    inline_max_mb: float,
    *,
    timeout_s: float | None = 60.0,
) -> Tuple[Any, str, Optional[str]]:
    size_mb = path.stat().st_size / (1024 * 1024)
    _, types = _lazy_import_gemini()
    mime = guess_mime(path)

    if size_mb <= inline_max_mb:
        data = path.read_bytes()
        part = types.Part.from_bytes(data=data, mime_type=mime)
        return part, mime, None

    try:
        file_ref = _invoke_with_timeout_hints(client.files.upload, {"file": str(path)}, timeout_s)
    except TimeoutError as exc:
        raise RuntimeError(f"Gemini file upload timed out: {exc}") from exc
    upload_name = getattr(file_ref, "name", None)
    return file_ref, mime, upload_name
