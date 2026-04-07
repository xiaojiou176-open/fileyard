from __future__ import annotations

import logging

from packages.observability import events


def test_event_context_forwards_defaults(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_set_defaults(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(events, "_set_log_context_defaults", fake_set_defaults)

    events.event_context(trace_id="trace-1", run_id="run-1")

    assert captured == {"trace_id": "trace-1", "run_id": "run-1"}


def test_emit_event_normalizes_failure_domain_enum(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_log_event(logger, level, event_name, message, **fields):
        captured.update(
            {
                "logger": logger,
                "level": level,
                "event": event_name,
                "message": message,
                "fields": fields,
            }
        )

    monkeypatch.setattr(events, "_log_event", fake_log_event)
    logger = logging.getLogger("events-test")

    events.emit_event(
        logger,
        logging.INFO,
        "review.queue.summary",
        "hello",
        failure_domain=events.FailureDomain.REPO_LOGIC,
        queue_size=3,
    )

    assert captured["logger"] is logger
    assert captured["level"] == logging.INFO
    assert captured["event"] == "review.queue.summary"
    assert captured["message"] == "hello"
    assert captured["fields"] == {
        "failure_domain": "repo_logic",
        "queue_size": 3,
    }
