import json
import logging

import pytest

from packages.observability import logging_utils
from packages.observability.logging_utils import log_event, set_log_context_defaults, setup_logger


def _fixture_path(*parts: str) -> str:
    return "/" + "/".join(("workspace-fixture", *parts))


@pytest.fixture(autouse=True)
def reset_logging_observability_context(monkeypatch):
    set_log_context_defaults(
        trace_id="",
        request_id="",
        session_id="",
        user_id="",
        workspace_id="",
        service="",
        component="",
    )
    for key in (
        "FILEMAN_TRACE_ID",
        "FILEMAN_REQUEST_ID",
        "FILEMAN_SESSION_ID",
        "FILEMAN_USER_ID",
        "FILEMAN_WORKSPACE_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)
    yield
    set_log_context_defaults(
        trace_id="",
        request_id="",
        session_id="",
        user_id="",
        workspace_id="",
        service="",
        component="",
    )


def test_log_event_json(capsys):
    logger = setup_logger("INFO", True)
    log_event(logger, logging.INFO, "unit_test", "hello", foo="bar")
    captured = capsys.readouterr().out.strip()
    payload = json.loads(captured)
    assert payload["event"] == "unit_test"
    assert payload["message"] == "hello"
    assert payload["fields"]["foo"] == "bar"


def test_log_event_json_redacts_path_by_default(capsys):
    logger = setup_logger("INFO", True)
    original_path = _fixture_path("private", "photos", "image.png")
    log_event(
        logger,
        logging.INFO,
        "unit_test",
        "hello",
        path=original_path,
    )
    captured = capsys.readouterr().out.strip()
    payload = json.loads(captured)
    assert payload["fields"]["path"] == ".../photos/image.png"


def test_log_event_json_can_disable_path_redaction(capsys):
    logger = setup_logger("INFO", True)
    original_path = _fixture_path("private", "photos", "image.png")
    log_event(
        logger,
        logging.INFO,
        "unit_test",
        "hello",
        redact_paths=False,
        path=original_path,
    )
    captured = capsys.readouterr().out.strip()
    payload = json.loads(captured)
    assert payload["fields"]["path"] == original_path


def test_log_event_json_redacts_path_in_message(capsys):
    logger = setup_logger("INFO", True)
    source_path = _fixture_path("private", "photos", "image.png")
    target_path = _fixture_path("runtime", "output", "a.png")
    log_event(
        logger,
        logging.INFO,
        "unit_test",
        f"MOVE {source_path} -> {target_path}",
    )
    captured = capsys.readouterr().out.strip()
    payload = json.loads(captured)
    assert source_path not in payload["message"]
    assert ".../photos/image.png" in payload["message"]


def test_log_event_text_mode_redacts_message_and_fields(capsys):
    logger = setup_logger("INFO", False)
    source_path = _fixture_path("private", "photos", "image.png")
    target_path = _fixture_path("runtime", "output", "a.png")
    log_event(
        logger,
        logging.INFO,
        "unit_test",
        f"MOVE {source_path} -> {target_path}",
        path=source_path,
    )
    captured = capsys.readouterr().out.strip()
    assert source_path not in captured
    assert ".../photos/image.png" in captured


def test_log_event_redacts_sensitive_fields_json(capsys):
    logger = setup_logger("INFO", True)
    log_event(
        logger,
        logging.INFO,
        "unit_test",
        "sensitive fields",
        token="abc123",
        secret="s3cr3t",
        password="p@ss",
        api_key="k-xxx",
        nested={"access_token": "nested-token", "safe": "ok"},
    )
    payload = json.loads(capsys.readouterr().out.strip())
    fields = payload["fields"]
    assert fields["token"] == "***"
    assert fields["secret"] == "***"
    assert fields["password"] == "***"
    assert fields["api_key"] == "***"
    assert fields["nested"]["access_token"] == "***"
    assert fields["nested"]["safe"] == "ok"


def test_log_event_redacts_sensitive_message_pairs(capsys):
    logger = setup_logger("INFO", True)
    log_event(
        logger,
        logging.INFO,
        "unit_test",
        "token=abc secret:xyz password=pwd api_key=k1 authorization=Bearer a1b2c3",
    )
    payload = json.loads(capsys.readouterr().out.strip())
    msg = payload["message"].lower()
    assert "token=***" in msg
    assert "secret=***" in msg
    assert "password=***" in msg
    assert "api_key=***" in msg
    assert "authorization=bearer ***" in msg
    assert "a1b2c3" not in msg


def test_log_event_auto_enriches_core_observability_fields(capsys):
    logger = setup_logger("INFO", True)
    log_event(logger, logging.INFO, "apply.move.start", "begin", run_id="apply_001", duration_s=1.234)
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["timestamp"]
    assert payload["run_id"] == "apply_001"
    assert payload["trace_id"] == "apply_001"
    assert payload["request_id"] == "apply_001"
    assert payload["session_id"] == "apply_001"
    assert payload["span_id"].startswith("spn_")
    assert payload["service"] == "fileman"
    assert payload["component"]
    assert payload["workspace_id"] == "default"
    assert payload["failure_domain"] == "repo_logic"
    assert payload["status"] == "start"
    assert payload["action"] == "apply.move"
    assert payload["duration_ms"] == 1234


def test_log_event_preserves_explicit_failure_domain_and_upstream(capsys):
    logger = setup_logger("INFO", True)
    log_event(
        logger,
        logging.ERROR,
        "apply.move.fail",
        "move failed",
        run_id="apply_004",
        failure_domain="upstream_image",
        upstream_id="ci-runtime-image",
        workspace_id="workspace-alpha",
        service="fileman-web-api",
        component="apply-worker",
        error_type="RuntimeError",
        error_code="apply_move_failed",
        error_message="move failed",
        error_retryable=False,
    )
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["failure_domain"] == "upstream_image"
    assert payload["upstream_id"] == "ci-runtime-image"
    assert payload["workspace_id"] == "workspace-alpha"
    assert payload["service"] == "fileman-web-api"
    assert payload["component"] == "apply-worker"
    assert payload["error"]["type"] == "RuntimeError"
    assert payload["error"]["code"] == "apply_move_failed"
    assert payload["error"]["message"] == "move failed"
    assert payload["error"]["retryable"] is False


def test_log_event_auto_builds_error_payload(capsys):
    logger = setup_logger("INFO", True)
    log_event(
        logger,
        logging.ERROR,
        "apply.move.fail",
        "move failed",
        run_id="apply_002",
        error_stack="stacktrace",
    )
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["status"] == "fail"
    assert payload["trace_id"] == "apply_002"
    assert payload["error"]["type"] == "UnknownError"
    assert payload["error"]["code"] == "UNKNOWN"
    assert payload["error"]["message"] == "move failed"
    assert payload["error"]["retryable"] is False


def test_log_event_builds_error_payload_from_exception_context(capsys):
    logger = setup_logger("INFO", True)
    exc = ValueError("broken payload")
    log_event(
        logger,
        logging.ERROR,
        "apply.move.fail",
        "move failed",
        run_id="apply_003",
        exc_info=exc,
    )
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["error"]["type"] == "ValueError"
    assert payload["error"]["message"] == "broken payload"
    assert isinstance(payload["error"]["stack"], str)


def test_log_event_uses_env_defaults_for_observability_ids(capsys, monkeypatch):
    monkeypatch.setenv("FILEMAN_TRACE_ID", "trace_env")
    monkeypatch.setenv("FILEMAN_REQUEST_ID", "req_env")
    monkeypatch.setenv("FILEMAN_SESSION_ID", "sess_env")
    monkeypatch.setenv("FILEMAN_USER_ID", "user_env")
    logger = setup_logger("INFO", True)

    log_event(logger, logging.INFO, "apply.move.start", "begin")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["trace_id"] == "trace_env"
    assert payload["request_id"] == "req_env"
    assert payload["session_id"] == "sess_env"
    assert payload["user_id"] == "user_env"


def test_log_event_keeps_explicit_gate_bridge_fields(capsys):
    logger = setup_logger("INFO", True)

    log_event(
        logger,
        logging.INFO,
        "apply.move.start",
        "begin",
        run_id="apply_005",
        gate_run_id="quality-gate-run-1",
        gate_name="quality-gate",
    )

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["run_id"] == "apply_005"
    assert payload["gate_run_id"] == "quality-gate-run-1"
    assert payload["gate_name"] == "quality-gate"


def test_log_event_explicit_fields_override_env_defaults(capsys, monkeypatch):
    monkeypatch.setenv("FILEMAN_TRACE_ID", "trace_env")
    monkeypatch.setenv("FILEMAN_REQUEST_ID", "req_env")
    monkeypatch.setenv("FILEMAN_SESSION_ID", "sess_env")
    monkeypatch.setenv("FILEMAN_USER_ID", "user_env")
    logger = setup_logger("INFO", True)

    log_event(
        logger,
        logging.INFO,
        "apply.move.start",
        "begin",
        trace_id="trace_call",
        request_id="req_call",
        session_id="sess_call",
        user_id="user_call",
    )

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["trace_id"] == "trace_call"
    assert payload["request_id"] == "req_call"
    assert payload["session_id"] == "sess_call"
    assert payload["user_id"] == "user_call"


def test_log_event_explicit_gate_bridge_fields_survive_with_other_defaults(capsys, monkeypatch):
    monkeypatch.setenv("FILEMAN_TRACE_ID", "trace_env")
    logger = setup_logger("INFO", True)

    log_event(
        logger,
        logging.INFO,
        "apply.move.start",
        "begin",
        gate_run_id="verify-repo-final-run-1",
        gate_name="verify-repo-final",
    )

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["gate_run_id"] == "verify-repo-final-run-1"
    assert payload["gate_name"] == "verify-repo-final"
    assert payload["trace_id"] == "trace_env"


def test_log_event_handles_empty_message_and_tuple_fields_in_text_mode(capsys):
    logger = setup_logger("INFO", False)
    first_path = _fixture_path("private", "a.png")
    second_path = _fixture_path("tmp", "b.png")
    log_event(
        logger,
        logging.INFO,
        "apply.move.retry",
        "",
        error=None,
        paths=(first_path, second_path),
    )
    out = capsys.readouterr().out.strip()
    assert "paths=('.../private/a.png', '.../tmp/b.png')" in out
    assert "error=" not in out
    assert "status=retry" in out


def test_log_event_empty_event_uses_unknown_action(capsys):
    logger = setup_logger("INFO", True)
    log_event(logger, logging.INFO, "unknown.success", "ok")
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["action"] == "unknown"
    assert payload["status"] == "success"


def test_log_event_resolves_exception_from_tuple_and_exc_alias(capsys):
    logger = setup_logger("INFO", True)
    tuple_exc = (ValueError, ValueError("tuple-boom"), None)
    log_event(logger, logging.ERROR, "apply.fail", "failed", exc_info=tuple_exc)
    payload_tuple = json.loads(capsys.readouterr().out.strip())
    assert payload_tuple["error"]["type"] == "ValueError"
    assert payload_tuple["error"]["message"] == "tuple-boom"

    log_event(logger, logging.ERROR, "apply.fail", "failed", exc=RuntimeError("alias-boom"))
    payload_alias = json.loads(capsys.readouterr().out.strip())
    assert payload_alias["error"]["type"] == "RuntimeError"
    assert payload_alias["error"]["message"] == "alias-boom"


def test_log_context_defaults_can_be_set_and_cleared(capsys):
    set_log_context_defaults(trace_id="cfg-trace", request_id="", session_id="cfg-session", user_id="")
    logger = setup_logger("INFO", True)
    log_event(logger, logging.INFO, "apply.move.start", "begin")
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["trace_id"] == "cfg-trace"
    assert payload["session_id"] == "cfg-session"

    set_log_context_defaults(trace_id="", session_id="", request_id="", user_id="")
    assert logging_utils._CONFIG_CONTEXT_DEFAULTS == {}
