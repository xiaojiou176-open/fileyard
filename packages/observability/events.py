from __future__ import annotations

from enum import Enum
from typing import Any

from packages.observability.logging_utils import (
    log_event as _log_event,
)
from packages.observability.logging_utils import (
    set_log_context_defaults as _set_log_context_defaults,
)


class FailureDomain(str, Enum):
    REPO_LOGIC = "repo_logic"
    REPO_CONFIG = "repo_config"
    WORKSPACE_INPUT = "workspace_input"
    CACHE_STATE = "cache_state"
    CI_ENVIRONMENT = "ci_environment"
    UPSTREAM_PYTHON = "upstream_python"
    UPSTREAM_NODE = "upstream_node"
    UPSTREAM_IMAGE = "upstream_image"
    UPSTREAM_BROWSER = "upstream_browser"
    UPSTREAM_MODEL = "upstream_model"


def event_context(**kwargs: Any) -> None:
    _set_log_context_defaults(**kwargs)


def emit_event(logger: Any, level: int, event: str, message: str, **fields: Any) -> None:
    failure_domain = fields.get("failure_domain")
    if isinstance(failure_domain, FailureDomain):
        fields["failure_domain"] = failure_domain.value
    _log_event(logger, level, event, message, **fields)
