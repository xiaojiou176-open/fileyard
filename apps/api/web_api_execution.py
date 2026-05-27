# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, Sequence

from apps.api.web_api_core import CommandExecutor
from apps.api.web_api_store import JobStore


class JobCancelled(RuntimeError):
    """Raised when a job is cooperatively cancelled."""


class EventSink:
    def __init__(self, store: JobStore, job_id: str) -> None:
        self._store = store
        self._job_id = job_id

    @property
    def job_id(self) -> str:
        return self._job_id

    def phase(self, phase_label: str, progress: float) -> None:
        self._store.update_phase(self._job_id, phase_label, progress)

    def info(self, message: str, **fields: Any) -> None:
        self._store.add_event(self._job_id, "info", message, **fields)

    def warn(self, message: str, **fields: Any) -> None:
        self._store.add_event(self._job_id, "warn", message, **fields)

    def error(self, message: str, **fields: Any) -> None:
        self._store.add_event(self._job_id, "error", message, **fields)

    def should_cancel(self) -> bool:
        return self._store.is_cancel_requested(self._job_id)

    def check_cancelled(self) -> None:
        if self.should_cancel():
            raise JobCancelled("cancel requested")


class CommandExecutionFacade:
    """Unified command execution facade for Web API jobs.

    The default implementation executes fileyard CLI subcommands via subprocess.
    """

    def __init__(self, command_executor: CommandExecutor | None = None) -> None:
        self._command_executor = command_executor or _default_command_executor
        self._accepts_cancel = len(inspect.signature(self._command_executor).parameters) >= 4

    @property
    def accepts_cancel(self) -> bool:
        return self._accepts_cancel

    def run(
        self,
        command: Sequence[str],
        cwd: Path,
        emit: Callable[[str, str, Dict[str, Any]], None],
        should_cancel: Callable[[], bool],
    ) -> None:
        if self._accepts_cancel:
            self._command_executor(command, cwd, emit, should_cancel)
            return
        self._command_executor(command, cwd, emit)


class JobRunner:
    def __init__(self, store: JobStore, command_executor: CommandExecutor | None = None) -> None:
        self._store = store
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="web-api-job")
        self._execution = CommandExecutionFacade(command_executor)
        self._executor_accepts_cancel = self._execution.accepts_cancel

    def submit(self, job_id: str, worker: Callable[[EventSink], Dict[str, Any]]) -> None:
        self._pool.submit(self._run, job_id, worker)

    def run_command(self, command: Sequence[str], cwd: Path, sink: EventSink) -> None:
        self._execution.run(
            command,
            cwd,
            lambda level, message, fields: self._log_from_executor(sink, level, message, fields),
            sink.should_cancel,
        )
        sink.check_cancelled()

    @staticmethod
    def _log_from_executor(sink: EventSink, level: str, message: str, fields: Dict[str, Any]) -> None:
        normalized = level.lower()
        if normalized == "error":
            sink.error(message, **fields)
        elif normalized == "warn":
            sink.warn(message, **fields)
        else:
            sink.info(message, **fields)

    def _run(self, job_id: str, worker: Callable[[EventSink], Dict[str, Any]]) -> None:
        sink = EventSink(self._store, job_id)
        if not self._store.mark_running(job_id):
            return
        try:
            sink.check_cancelled()
            summary = worker(sink)
            sink.check_cancelled()
            self._store.mark_succeeded(job_id, summary)
        except JobCancelled as exc:
            self._store.mark_cancelled(job_id, str(exc))
        except Exception as exc:  # pragma: no cover - defensive path
            self._store.mark_failed(job_id, str(exc))


def _default_command_executor(
    command: Sequence[str],
    cwd: Path,
    emit: Callable[[str, str, Dict[str, Any]], None],
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    if should_cancel and should_cancel():
        emit("warn", "command_cancelled_before_start", {})
        raise JobCancelled("cancel requested before command start")
    emit("info", "command_start", {"command": " ".join(shlex.quote(part) for part in command)})
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for raw_line in process.stdout:
        if should_cancel and should_cancel():
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
            emit("warn", "command_cancelled", {})
            raise JobCancelled("cancel requested during command execution")
        line = raw_line.rstrip()
        if line:
            emit("info", "command_output", {"line": line})
    return_code = process.wait()
    if should_cancel and should_cancel():
        emit("warn", "command_cancelled_after_wait", {})
        raise JobCancelled("cancel requested")
    if return_code != 0:
        emit("error", "command_failed", {"return_code": return_code})
        raise RuntimeError(f"command failed with exit code {return_code}")
    emit("info", "command_success", {"return_code": return_code})
