# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path, PurePath
from typing import Any, Callable, Dict, List, Literal, Sequence

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from apps.api.web_api_core import (
    CommandExecutor,
    _now_iso,
    _parse_form_bool,
    _read_json_file,
    _read_manifest_rows,
    _safe_float_progress,
    _safe_relative_descendant,
    _sanitize_filename,
    _within_root,
    _write_json_atomic,
    _write_jsonl_rows,
)
from apps.api.web_api_execution import EventSink, JobCancelled, JobRunner, _default_command_executor
from apps.api.web_api_models import (
    TERMINAL_JOB_STATUSES,
    AnalyzeJsonRequest,
    ApplyRequest,
    InboxAnalyzeRequest,
    JobKind,
    JobRecord,
    JobView,
    ManifestBatchRequest,
    ManifestConflictResolveRequest,
    ManifestRowPatchRequest,
    PreferenceUpsertRequest,
    ReviewQueueBatchTriageRequest,
    ReviewRuleApplyRequest,
    ReviewRuleFromExamplesRequest,
    ReviewRuleUpsertRequest,
    RollbackRequest,
    RuntimeAnalyzeDefaultsView,
    RuntimeSettingsUpdateRequest,
    RuntimeSettingsView,
    WatchSourceUpsertRequest,
)
from apps.api.web_api_routes import (
    MANIFEST_EDITABLE_EXTRA_FIELDS,
    apply_overlay_rows,
    build_preview_payload,
    coerce_row_index,
    detect_manifest_conflicts,
    get_manifest_path_for_job,
    load_overlay,
    read_preference_items,
    resolve_manifest_path,
    save_overlay,
    sse,
    validate_manifest_for_rollback,
    write_preference_items,
)
from apps.api.web_api_store import JobStore
from packages.application.collection_intelligence import apply_collection_intelligence
from packages.application.inbox_watch import scan_watch_sources_once
from packages.application.review_copilot import build_review_copilot_summary
from packages.application.review_learning import learn_category_rules, suggest_for_row
from packages.application.review_rules import apply_rule_to_overlay, build_rule_draft_from_examples, preview_rules
from packages.domain.normalization import normalize_categories
from packages.domain.pipeline_config import DEFAULT_CATEGORIES, DEFAULT_MAX_FILE_MB, DEFAULT_WORKERS
from packages.domain.review_queue import build_review_queue_summary, evaluate_review_bucket
from packages.domain.review_rules import ReviewRule
from packages.domain.rollback_integrity import _has_strong_rollback_signing_key
from packages.domain.strategy_pack_registry import strategy_pack_by_id
from packages.infrastructure.learned_rule_store import load_learned_rules, save_learned_rules
from packages.infrastructure.manifest_store import read_jsonl
from packages.infrastructure.preference_store import (
    migrate_legacy_named_items,
)
from packages.infrastructure.preference_store import (
    preference_root as _workspace_preference_root,
)
from packages.infrastructure.preference_store import (
    read_named_items as _read_named_preference_items,
)
from packages.infrastructure.preference_store import (
    write_named_items as _write_named_preference_items,
)
from packages.infrastructure.runtime_env import mask_secret
from packages.infrastructure.runtime_env_store import (
    read_runtime_env_map as _shared_read_runtime_env_map,
)
from packages.infrastructure.runtime_env_store import (
    runtime_env_file as _shared_runtime_env_file,
)
from packages.infrastructure.runtime_env_store import (
    write_runtime_env_values as _shared_write_runtime_env_values,
)
from packages.infrastructure.strategy_pack_store import (
    get_active_strategy_pack_id,
    list_strategy_pack_payloads,
    set_active_strategy_pack_id,
)
from packages.infrastructure.watch_source_store import WatchSource, load_watch_sources, save_watch_sources


def _discover_repo_root() -> Path:
    candidates = [Path.cwd().resolve(), *Path(__file__).resolve().parents]
    for candidate in candidates:
        has_cli = (candidate / "apps" / "cli" / "fileman.py").exists()
        has_schema = (candidate / "contracts" / "runtime" / "manifest.schema.json").exists()
        if has_cli and has_schema:
            return candidate
    return Path(__file__).resolve().parents[3]


PIPELINE_ROOT = Path(__file__).resolve().parent
PACKAGES_ROOT = PIPELINE_ROOT.parent
REPO_ROOT = _discover_repo_root()
CLI_ENTRYPOINT = REPO_ROOT / "apps" / "cli" / "fileman.py"
WORKSPACE_ROOT = Path(os.environ.get("FILEMAN_WORKSPACE_ROOT", "~/.fileman/workspaces/default")).expanduser()
DEFAULT_INPUT_ROOT = Path(os.environ.get("FILEMAN_INPUT_ROOT", str(WORKSPACE_ROOT / "data" / "raw"))).expanduser()
DEFAULT_OUTPUT_ROOT = Path(os.environ.get("FILEMAN_OUTPUT_ROOT", str(WORKSPACE_ROOT / "data" / "organized"))).expanduser()
MANIFEST_ROOT = Path(os.environ.get("FILEMAN_MANIFEST_ROOT", str(WORKSPACE_ROOT / ".fileman" / "manifests"))).expanduser()
ARTIFACT_ROOT = Path(os.environ.get("FILEMAN_ARTIFACT_ROOT", str(WORKSPACE_ROOT / ".fileman" / "artifacts"))).expanduser()
DEFAULT_ALLOWED_ROOT = os.environ.get(
    "FILEMAN_ALLOWED_ROOT",
    f"{DEFAULT_INPUT_ROOT},{DEFAULT_OUTPUT_ROOT}",
)

WEB_ARTIFACT_ROOT = ARTIFACT_ROOT / "web_api"
WEB_JOB_ROOT = WEB_ARTIFACT_ROOT / "jobs"
WEB_UPLOAD_ROOT = WEB_ARTIFACT_ROOT / "uploads"
PREFERENCE_ROOT = _workspace_preference_root(WORKSPACE_ROOT)
REPORT_ROOT = ARTIFACT_ROOT / "report"
ROLLBACK_ROOT = ARTIFACT_ROOT / "rollback"
FRONTEND_DIST_ROOT = REPO_ROOT / ".runtime-cache" / "build" / "apps" / "webui"
RUNTIME_SETTINGS_KEYS = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "FILEMAN_INPUT_ROOT",
    "FILEMAN_OUTPUT_ROOT",
    "FILEMAN_ROLLBACK_HMAC_KEY",
)
UPLOAD_COPY_CHUNK_SIZE = 1024 * 1024
RUNTIME_DEFAULTS_FILENAME = "runtime_defaults.json"
DEFAULT_RUNTIME_MAX_FILES = 5000
DEFAULT_RUNTIME_MAX_TOTAL_MB = 10240.0

__all__ = [
    "EventSink",
    "JobCancelled",
    "JobKind",
    "JobRecord",
    "JobRunner",
    "JobStore",
    "JobView",
    "TERMINAL_JOB_STATUSES",
    "_default_command_executor",
    "_safe_float_progress",
    "create_app",
]


def _resolve_manifest_path(store: JobStore, analyze_job_id: str | None, manifest_path: str | None) -> Path:
    allowed_roots = [MANIFEST_ROOT, WEB_JOB_ROOT, REPORT_ROOT, ROLLBACK_ROOT]
    return resolve_manifest_path(
        store,
        analyze_job_id,
        manifest_path,
        allowed_roots=allowed_roots,
        within_root=_within_root,
    )


def _resolve_internal_artifact_path(raw: str | Path, *, root: Path, field_name: str) -> Path:
    return _resolve_root_descendant_candidate(
        raw,
        allowed_roots=[root],
        field_name=field_name,
        require_exists=False,
        require_directory=None,
    )


def _resolve_existing_operator_directory(raw: str | Path, *, field_name: str) -> Path:
    candidate = Path(str(raw or "")).expanduser()
    try:
        resolved = candidate.absolute()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} is invalid") from exc
    if _is_filesystem_root(resolved):
        raise HTTPException(status_code=400, detail=f"{field_name} must not be the filesystem root")
    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"{field_name} must exist")
    return resolved


def _normalize_operator_directory_input(raw: str | Path, *, field_name: str) -> Path:
    candidate = Path(str(raw or "")).expanduser()
    try:
        resolved = candidate.absolute()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} is invalid") from exc
    if _is_filesystem_root(resolved):
        raise HTTPException(status_code=400, detail=f"{field_name} must not be the filesystem root")
    return resolved


def _resolve_existing_internal_file(raw: str | Path, *, root: Path, field_name: str) -> Path:
    return _resolve_root_descendant_candidate(
        raw,
        allowed_roots=[root],
        field_name=field_name,
        require_exists=True,
        require_directory=False,
    )


def _resolve_root_descendant_path(raw: str | None, *, root: Path, field_name: str) -> Path:
    relative = _safe_relative_descendant(raw)
    candidate = root / relative
    if not _within_root(candidate, root):
        raise HTTPException(status_code=400, detail=f"{field_name} is outside controlled roots")
    return root.resolve() / relative


def _resolve_root_descendant_candidate(
    raw: str | Path | None,
    *,
    allowed_roots: Sequence[Path],
    field_name: str,
    require_exists: bool,
    require_directory: bool | None,
) -> Path:
    raw_text = os.path.expanduser(str(raw or "").strip())
    candidate = PurePath(raw_text)
    roots = [root.resolve() for root in allowed_roots]
    descendants: list[Path] = []
    if candidate.is_absolute():
        absolute_parts = candidate.parts
        for root in roots:
            root_parts = PurePath(str(root)).parts
            if tuple(absolute_parts[: len(root_parts)]) != tuple(root_parts):
                continue
            remainder = absolute_parts[len(root_parts) :]
            if any(part in {"", ".", ".."} for part in remainder):
                continue
            descendants.append(root.joinpath(*remainder))
    else:
        relative = _safe_relative_descendant(raw_text)
        descendants = [root / relative for root in roots]

    if not descendants:
        raise HTTPException(status_code=400, detail=f"{field_name} is outside controlled roots")

    saw_allowed_candidate = False
    for unresolved in descendants:
        try:
            resolved = unresolved.resolve(strict=False)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"{field_name} is invalid") from exc
        if not any(_within_root(resolved, root) for root in roots):
            continue
        saw_allowed_candidate = True
        if require_exists and not resolved.exists():
            continue
        if require_directory is True and resolved.exists() and not resolved.is_dir():
            raise HTTPException(status_code=400, detail=f"{field_name} must exist")
        if require_directory is False and resolved.exists() and not resolved.is_file():
            raise HTTPException(status_code=404, detail=f"{field_name} is missing")
        return resolved

    if saw_allowed_candidate and require_exists:
        if require_directory is True:
            raise HTTPException(status_code=400, detail=f"{field_name} must exist")
        if require_directory is False:
            raise HTTPException(status_code=404, detail=f"{field_name} is missing")
    raise HTTPException(status_code=400, detail=f"{field_name} is outside controlled roots")


def _runtime_env_path() -> Path:
    return _shared_runtime_env_file(WORKSPACE_ROOT)


def _preference_root() -> Path:
    return PREFERENCE_ROOT


def _read_named_preference(name: str) -> Dict[str, Dict[str, Any]]:
    return _read_named_preference_items(WORKSPACE_ROOT, name)


def _write_named_preference(name: str, items: Dict[str, Dict[str, Any]]) -> Path:
    return _write_named_preference_items(WORKSPACE_ROOT, name, items, updated_at=_now_iso())


def _read_runtime_env_map() -> Dict[str, str]:
    return _shared_read_runtime_env_map(WORKSPACE_ROOT)


def _write_runtime_env_map(values: Dict[str, str]) -> Path:
    current = _read_runtime_env_map()
    updates: Dict[str, str | None] = {}
    for key in set(current) | set(values):
        updates[key] = values.get(key)
    return _shared_write_runtime_env_values(updates, workspace_root=WORKSPACE_ROOT)


def _resolve_runtime_value(name: str, default: str = "") -> tuple[str, Literal["env", "runtime_env", "default", "missing"]]:
    process_value = str(os.environ.get(name, "") or "").strip()
    if process_value:
        return process_value, "env"
    file_value = str(_read_runtime_env_map().get(name, "") or "").strip()
    if file_value:
        return file_value, "runtime_env"
    if default:
        return default, "default"
    return "", "missing"


def _looks_like_placeholder_secret(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return False
    markers = ("dummy", "test", "mock", "fake", "sample", "changeme", "placeholder")
    return len(normalized) < 12 or any(marker in normalized for marker in markers)


def _normalize_runtime_path(raw: str | None, fallback: Path) -> Path:
    candidate = str(raw or "").strip()
    if not candidate:
        return fallback.resolve()
    resolved = _resolve_root_descendant_candidate(
        candidate,
        allowed_roots=[WORKSPACE_ROOT],
        field_name="runtime path",
        require_exists=False,
        require_directory=None,
    )
    if resolved == WORKSPACE_ROOT:
        return fallback.resolve()
    return resolved


def _resolve_controlled_runtime_root(
    raw: str | None,
    fallback: Path,
    *,
    field_name: str,
    allow_missing: bool = False,
) -> Path:
    target = _normalize_runtime_path(raw, fallback)
    if _is_filesystem_root(target):
        raise HTTPException(status_code=400, detail=f"{field_name} must not be the filesystem root")
    if not _within_root(target, WORKSPACE_ROOT):
        raise HTTPException(status_code=400, detail=f"{field_name} must stay under the workspace root")
    if not allow_missing and (not target.exists() or not target.is_dir()):
        raise HTTPException(status_code=400, detail=f"{field_name} must exist")
    return target


def _runtime_defaults_path() -> Path:
    return _preference_root() / RUNTIME_DEFAULTS_FILENAME


def _migrate_preference_roots() -> None:
    for name in ("views", "naming_templates", "review_rules", "strategy_packs"):
        migrate_legacy_named_items(WORKSPACE_ROOT, name, updated_at=_now_iso())
    legacy_runtime_defaults = ARTIFACT_ROOT / "web_api" / "preferences" / RUNTIME_DEFAULTS_FILENAME
    target = _runtime_defaults_path()
    if target.exists() or not legacy_runtime_defaults.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(legacy_runtime_defaults.read_text(encoding="utf-8"), encoding="utf-8")


def _default_runtime_analyze_defaults() -> Dict[str, Any]:
    return {
        "workers": DEFAULT_WORKERS,
        "categories": list(DEFAULT_CATEGORIES),
        "max_files": DEFAULT_RUNTIME_MAX_FILES,
        "max_total_mb": DEFAULT_RUNTIME_MAX_TOTAL_MB,
        "max_file_mb": DEFAULT_MAX_FILE_MB,
    }


def _coerce_runtime_categories(raw: Any) -> List[str]:
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
        return normalize_categories(items) if items else list(DEFAULT_CATEGORIES)
    if isinstance(raw, str):
        items = [part.strip() for part in raw.split(",") if part.strip()]
        return normalize_categories(items) if items else list(DEFAULT_CATEGORIES)
    return list(DEFAULT_CATEGORIES)


def _read_runtime_analyze_defaults() -> Dict[str, Any]:
    defaults = _default_runtime_analyze_defaults()
    payload = _read_json_file(_runtime_defaults_path(), {})
    if not isinstance(payload, dict):
        return defaults
    stored = payload.get("analyze_defaults", payload)
    if not isinstance(stored, dict):
        return defaults
    workers = int(stored.get("workers", defaults["workers"]) or defaults["workers"])
    max_files = int(stored.get("max_files", defaults["max_files"]) or defaults["max_files"])
    max_total_mb = float(stored.get("max_total_mb", defaults["max_total_mb"]) or defaults["max_total_mb"])
    max_file_mb = float(stored.get("max_file_mb", defaults["max_file_mb"]) or defaults["max_file_mb"])
    return {
        "workers": max(workers, 1),
        "categories": _coerce_runtime_categories(stored.get("categories")),
        "max_files": max(max_files, 0),
        "max_total_mb": max(max_total_mb, 0.0),
        "max_file_mb": max(max_file_mb, 0.0),
    }


def _write_runtime_analyze_defaults(defaults: Dict[str, Any]) -> None:
    target = _runtime_defaults_path()
    _write_json_atomic(
        target,
        {
            "updated_at": _now_iso(),
            "analyze_defaults": defaults,
        },
        root=target.parent,
    )


def _is_filesystem_root(path: Path) -> bool:
    return path.resolve().parent == path.resolve()


def _refresh_runtime_defaults(*, input_root: Path | None = None, output_root: Path | None = None) -> None:
    global DEFAULT_INPUT_ROOT, DEFAULT_OUTPUT_ROOT, DEFAULT_ALLOWED_ROOT
    if input_root is not None:
        DEFAULT_INPUT_ROOT = input_root
        os.environ["FILEMAN_INPUT_ROOT"] = str(DEFAULT_INPUT_ROOT)
    if output_root is not None:
        DEFAULT_OUTPUT_ROOT = output_root
        os.environ["FILEMAN_OUTPUT_ROOT"] = str(DEFAULT_OUTPUT_ROOT)
    DEFAULT_ALLOWED_ROOT = f"{DEFAULT_INPUT_ROOT},{DEFAULT_OUTPUT_ROOT}"


def _bootstrap_runtime_defaults() -> None:
    runtime_env_values = _read_runtime_env_map()
    input_root = _normalize_runtime_path(runtime_env_values.get("FILEMAN_INPUT_ROOT"), DEFAULT_INPUT_ROOT)
    output_root = _normalize_runtime_path(runtime_env_values.get("FILEMAN_OUTPUT_ROOT"), DEFAULT_OUTPUT_ROOT)
    _refresh_runtime_defaults(input_root=input_root, output_root=output_root)


def _runtime_settings_view() -> RuntimeSettingsView:
    api_key, api_key_source = _resolve_runtime_value("GEMINI_API_KEY", "")
    model_default = "gemini-3-flash-preview"
    model, model_source = _resolve_runtime_value("GEMINI_MODEL", model_default)
    active_strategy_pack_id = get_active_strategy_pack_id(WORKSPACE_ROOT)
    input_root_raw, _ = _resolve_runtime_value("FILEMAN_INPUT_ROOT", str(DEFAULT_INPUT_ROOT))
    output_root_raw, _ = _resolve_runtime_value("FILEMAN_OUTPUT_ROOT", str(DEFAULT_OUTPUT_ROOT))
    input_root = _normalize_runtime_path(input_root_raw, DEFAULT_INPUT_ROOT)
    output_root = _normalize_runtime_path(output_root_raw, DEFAULT_OUTPUT_ROOT)
    analyze_defaults = _read_runtime_analyze_defaults()
    active_pack = strategy_pack_by_id(REPO_ROOT, active_strategy_pack_id) if active_strategy_pack_id else None
    if active_pack is not None:
        analyze_defaults = {
            **analyze_defaults,
            "categories": list(active_pack.categories) or analyze_defaults["categories"],
            "workers": active_pack.workers or analyze_defaults["workers"],
        }
        if active_pack.model and model_source == "missing":
            model = active_pack.model
            model_source = "default"

    warnings: List[str] = []
    missing: List[str] = []
    api_key_status: Literal["configured", "missing", "placeholder"] = "configured"  # pragma: allowlist secret
    if not api_key:
        api_key_status = "missing"  # pragma: allowlist secret
        missing.append("GEMINI_API_KEY")  # pragma: allowlist secret
    elif _looks_like_placeholder_secret(api_key):
        api_key_status = "placeholder"  # pragma: allowlist secret
        warnings.append("API Key still looks like a placeholder")
        missing.append("GEMINI_API_KEY")  # pragma: allowlist secret

    if not model:
        missing.append("GEMINI_MODEL")
    if not input_root.exists():
        warnings.append("Photo source folder does not exist yet")
        missing.append("FILEMAN_INPUT_ROOT")
    if not output_root.exists():
        warnings.append("Organized output folder does not exist yet")
        missing.append("FILEMAN_OUTPUT_ROOT")

    ready = len(missing) == 0
    if api_key_source == "env":  # pragma: allowlist secret
        normalized_api_key_source: Literal["env", "runtime_env", "missing"] = "env"
    elif api_key_source == "runtime_env":  # pragma: allowlist secret
        normalized_api_key_source = "runtime_env"  # pragma: allowlist secret
    else:
        normalized_api_key_source = "missing"  # pragma: allowlist secret
    return RuntimeSettingsView(
        workspace_root=str(WORKSPACE_ROOT),
        runtime_env_path=str(_runtime_env_path()),
        input_root=str(input_root),
        output_root=str(output_root),
        allowed_root=f"{input_root},{output_root}",
        manifest_root=str(MANIFEST_ROOT),
        artifact_root=str(ARTIFACT_ROOT),
        has_api_key=bool(api_key),
        api_key_masked=mask_secret(api_key),
        api_key_source=normalized_api_key_source,
        api_key_status=api_key_status,
        model=model,
        model_source="default" if model_source == "missing" else model_source,
        active_strategy_pack_id=active_strategy_pack_id,
        input_root_exists=input_root.exists(),
        output_root_exists=output_root.exists(),
        ready=ready,
        analyze_defaults=RuntimeAnalyzeDefaultsView(**analyze_defaults),
        missing=missing,
        warnings=warnings,
        checked_at=_now_iso(),
    )


def _effective_strategy_pack_defaults(
    pack_id: str | None,
    runtime_settings: RuntimeSettingsView,
    runtime_defaults: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
    effective_defaults = dict(runtime_defaults)
    target_pack_id = str(pack_id or "").strip()
    if not target_pack_id:
        return effective_defaults, None
    pack = strategy_pack_by_id(REPO_ROOT, target_pack_id)
    if pack is None:
        return effective_defaults, None
    effective_defaults["model"] = pack.model or runtime_settings.model
    effective_defaults["categories"] = list(pack.categories) or list(runtime_defaults.get("categories", []))
    effective_defaults["workers"] = pack.workers or int(runtime_defaults.get("workers", 1) or 1)
    effective_defaults["review_confidence_threshold"] = pack.review_confidence_threshold
    effective_defaults["default_template_patterns"] = list(pack.default_template_patterns)
    return effective_defaults, pack.to_dict()


def _build_analyze_enqueue_payload(
    source_dir: Path,
    *,
    artifacts_factory: Callable[[], tuple[Path, Path, Path]],
    runtime_settings: RuntimeSettingsView,
    runtime_defaults: Dict[str, Any],
    strategy_pack_id: str | None = None,
    watch_source_id: str | None = None,
    trigger_source: str = "manual",
    model: str | None = None,
    categories: str | None = None,
    workers: int | None = None,
    max_files: int | None = None,
    max_total_mb: float | None = None,
    max_file_mb: float | None = None,
    offline: bool = False,
) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
    effective_defaults, pack_payload = _effective_strategy_pack_defaults(strategy_pack_id, runtime_settings, runtime_defaults)
    manifest_path, csv_path, report_path = artifacts_factory()
    return (
        {
            "input_mode": "directory",
            "source_dir": str(source_dir),
            "manifest_path": str(manifest_path),
            "csv_path": str(csv_path),
            "report_path": str(report_path),
            "model": str(model or effective_defaults.get("model") or runtime_settings.model).strip(),
            "categories": str(categories or ",".join(effective_defaults["categories"])).strip(),
            "workers": max(int(workers or effective_defaults["workers"] or 1), 1),
            "max_files": effective_defaults["max_files"] if max_files is None else max_files,
            "max_total_mb": effective_defaults["max_total_mb"] if max_total_mb is None else max_total_mb,
            "max_file_mb": effective_defaults["max_file_mb"] if max_file_mb is None else max_file_mb,
            "offline": bool(offline),
            "trigger_source": trigger_source,
            "watch_source_id": str(watch_source_id or "").strip(),
            "strategy_pack_id": str(pack_payload.get("id", "") if pack_payload else strategy_pack_id or "").strip(),
            "strategy_pack_name": str(pack_payload.get("name", "") if pack_payload else "").strip(),
        },
        pack_payload,
    )


def _build_inbox_batch_view(batch: Any, source: WatchSource, runtime_settings: RuntimeSettingsView) -> Dict[str, Any]:
    runtime_defaults = runtime_settings.analyze_defaults.model_dump()
    effective_defaults, pack_payload = _effective_strategy_pack_defaults(
        source.strategy_pack_id or runtime_settings.active_strategy_pack_id,
        runtime_settings,
        runtime_defaults,
    )
    return {
        **batch.to_dict(),
        "watch_source_name": source.name,
        "discovery_mode": "scan_only",
        "analyze_ready": True,
        "strategy_pack": pack_payload,
        "analyze_defaults": {
            "model": str(effective_defaults.get("model", runtime_settings.model) or runtime_settings.model),
            "categories": ",".join(effective_defaults["categories"]),
            "workers": int(effective_defaults["workers"] or 1),
            "max_files": effective_defaults["max_files"],
            "max_total_mb": effective_defaults["max_total_mb"],
            "max_file_mb": effective_defaults["max_file_mb"],
            "offline": False,
        },
        "analyze_action": {
            "method": "POST",
            "path": "/api/inbox/analyze",
            "payload": {
                "watch_source_id": source.id,
                "batch_id": batch.id,
                "strategy_pack_id": str(source.strategy_pack_id or "").strip() or None,
            },
        },
    }


def _build_report_review_bridge(
    job_id: str,
    queue_summary: Dict[str, Any],
    collections: Sequence[Dict[str, Any]],
    copilot_summary: Dict[str, Any],
) -> Dict[str, Any]:
    needs_review = int(queue_summary.get("needs_review", 0) or 0)
    conflicts = int(queue_summary.get("conflict", 0) or 0)
    blocked = int(queue_summary.get("blocked", 0) or 0)
    next_step = "open_review_queue"
    if conflicts:
        next_step = "resolve_conflicts_in_review"
    elif needs_review == 0 and blocked == 0:
        next_step = "review_queue_optional"
    return {
        "mode": "review_first",
        "next_step": next_step,
        "review_queue_path": f"/api/jobs/{job_id}/review-queue",
        "batch_triage_path": f"/api/jobs/{job_id}/review-queue/batch-triage",
        "rule_from_examples_path": f"/api/jobs/{job_id}/review-rules/from-examples",
        "needs_review_count": needs_review,
        "conflict_count": conflicts,
        "blocked_count": blocked,
        "collection_focus_ids": [str(item.get("id", "") or "") for item in collections[:3] if str(item.get("id", "") or "")],
        "rule_opportunity_keys": [
            str(item.get("key", "") or "")
            for item in list(copilot_summary.get("rule_opportunities", []) or [])[:3]
            if str(item.get("key", "") or "")
        ],
        "execute_allowed": False,
    }


def _update_runtime_settings(payload: RuntimeSettingsUpdateRequest) -> RuntimeSettingsView:
    runtime_env_values = _read_runtime_env_map()
    current_settings = _runtime_settings_view()

    next_model = str(payload.model).strip() if payload.model is not None else current_settings.model
    if next_model and not next_model.lower().startswith("gemini-"):
        raise HTTPException(status_code=400, detail="model must start with gemini-")
    next_input_root = _resolve_controlled_runtime_root(
        payload.input_root,
        Path(current_settings.input_root),
        field_name="input_root",
        allow_missing=True,
    )
    next_output_root = _resolve_controlled_runtime_root(
        payload.output_root,
        Path(current_settings.output_root),
        field_name="output_root",
        allow_missing=True,
    )
    if payload.create_missing_dirs:
        next_input_root.mkdir(parents=True, exist_ok=True)
        next_output_root.mkdir(parents=True, exist_ok=True)

    if payload.clear_api_key:
        runtime_env_values.pop("GEMINI_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)
    if payload.api_key is not None and str(payload.api_key).strip():
        next_api_key = str(payload.api_key).strip()
        runtime_env_values["GEMINI_API_KEY"] = next_api_key
        os.environ["GEMINI_API_KEY"] = next_api_key
    runtime_env_values["GEMINI_MODEL"] = next_model
    runtime_env_values["FILEMAN_INPUT_ROOT"] = str(next_input_root)
    runtime_env_values["FILEMAN_OUTPUT_ROOT"] = str(next_output_root)
    os.environ["GEMINI_MODEL"] = next_model
    _write_runtime_env_map(runtime_env_values)
    next_strategy_pack_id = str(payload.active_strategy_pack_id or current_settings.active_strategy_pack_id or "").strip()
    if next_strategy_pack_id:
        set_active_strategy_pack_id(WORKSPACE_ROOT, next_strategy_pack_id, updated_at=_now_iso())
    _refresh_runtime_defaults(input_root=next_input_root, output_root=next_output_root)
    current_defaults = current_settings.analyze_defaults.model_dump()
    next_workers = int(payload.workers if payload.workers is not None else current_defaults["workers"] or DEFAULT_WORKERS)
    next_categories = _coerce_runtime_categories(payload.categories if payload.categories is not None else current_defaults["categories"])
    next_max_files = int(payload.max_files if payload.max_files is not None else current_defaults["max_files"])
    next_max_total_mb = float(payload.max_total_mb if payload.max_total_mb is not None else current_defaults["max_total_mb"])
    next_max_file_mb = float(payload.max_file_mb if payload.max_file_mb is not None else current_defaults["max_file_mb"])
    _write_runtime_analyze_defaults(
        {
            "workers": max(next_workers, 1),
            "categories": next_categories,
            "max_files": max(next_max_files, 0),
            "max_total_mb": max(next_max_total_mb, 0.0),
            "max_file_mb": max(next_max_file_mb, 0.0),
        }
    )
    return _runtime_settings_view()


def _parse_form_int(value: Any, field_name: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be an integer") from exc


def _parse_form_float(value: Any, field_name: str) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a number") from exc


def _sanitize_relative_upload_path(raw: str | None, fallback_name: str, index: int) -> Path:
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return Path(_sanitize_filename(fallback_name, index))
    parts = []
    for segment in text.split("/"):
        cleaned = Path(segment).name.strip()
        if not cleaned or cleaned in {".", ".."}:
            continue
        parts.append(cleaned)
    if not parts:
        return Path(_sanitize_filename(fallback_name, index))
    return Path(*parts[-8:])


def _ensure_controlled_directory(path: Path) -> None:
    controlled_roots = [DEFAULT_INPUT_ROOT, WEB_UPLOAD_ROOT]
    if not any(_within_root(path, root) for root in controlled_roots):
        raise HTTPException(status_code=400, detail="input directory is outside controlled roots")
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail="input directory must exist")


def _ensure_controlled_output_root(path: Path) -> None:
    if not _within_root(path, DEFAULT_OUTPUT_ROOT):
        raise HTTPException(status_code=400, detail="output root is outside controlled roots")


def _resolve_controlled_input_directory(raw: str | None, fallback: Path) -> Path:
    target = _resolve_root_descendant_candidate(
        raw or fallback,
        allowed_roots=[DEFAULT_INPUT_ROOT, WEB_UPLOAD_ROOT],
        field_name="input directory",
        require_exists=True,
        require_directory=True,
    )
    _ensure_controlled_directory(target)
    return target


def _resolve_controlled_output_directory(raw: str | None, fallback: Path) -> Path:
    target = _resolve_root_descendant_candidate(
        raw or fallback,
        allowed_roots=[DEFAULT_OUTPUT_ROOT],
        field_name="output root",
        require_exists=False,
        require_directory=None,
    )
    _ensure_controlled_output_root(target)
    return target


def _resolve_watch_source_root(source_id: str, *, field_name: str) -> Path:
    source = next((item for item in load_watch_sources(WORKSPACE_ROOT) if item.id == source_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail="watch source not found")
    return _resolve_existing_operator_directory(source.input_root, field_name=field_name)


def _resolve_apply_input_root(store: JobStore, analyze_job_id: str | None) -> Path:
    if analyze_job_id:
        source = store.get(analyze_job_id)
        if source is not None:
            source_input_root = str(source.summary.get("input_root", "") or source.payload.get("source_dir", "")).strip()
            if source_input_root:
                watch_source_id = str(source.payload.get("watch_source_id", "") or "").strip()
                trigger_source = str(source.payload.get("trigger_source", "") or "").strip()
                if watch_source_id or trigger_source == "inbox":
                    if watch_source_id:
                        source_root = _resolve_watch_source_root(watch_source_id, field_name="input_root")
                    else:
                        source_root = _resolve_existing_operator_directory(
                            source_input_root,
                            field_name="input_root",
                        )
                    return _resolve_root_descendant_candidate(
                        source_input_root,
                        allowed_roots=[source_root],
                        field_name="input_root",
                        require_exists=True,
                        require_directory=True,
                    )
                return _resolve_controlled_input_directory(source_input_root, DEFAULT_INPUT_ROOT.resolve())
    return DEFAULT_INPUT_ROOT.resolve()


def _validate_manifest_for_rollback(manifest_path: Path) -> None:
    validate_manifest_for_rollback(manifest_path, _read_manifest_rows)


def _build_cli_command(subcommand: str, *args: str, run_id: str | None = None) -> List[str]:
    command = [sys.executable, str(CLI_ENTRYPOINT), subcommand]
    if str(run_id or "").strip():
        command.extend(["--run-id", str(run_id)])
    command.extend(args)
    return command


def _job_to_view(record: JobRecord) -> JobView:
    payload: Dict[str, Any] = {
        "id": record.id,
        "kind": record.kind,
        "status": record.status,
        "phase_label": record.phase_label,
        "phase": record.phase_label,
        "progress": record.progress,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "retry_of": record.retry_of,
        "cancel_requested_at": record.cancel_requested_at,
        "summary": record.summary,
        "latest_error": record.latest_error,
    }
    return JobView(**payload)


def _load_overlay(overlay_path: Path, job_id: str) -> Dict[str, Any]:
    return load_overlay(_read_json_file, _now_iso, overlay_path, job_id)


def _save_overlay(overlay_path: Path, job_id: str, rows: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return save_overlay(_write_json_atomic, _now_iso, overlay_path, job_id, rows)


def _coerce_row_index(row_id: str, rows: Sequence[Dict[str, Any]]) -> int:
    return coerce_row_index(row_id, rows)


def _load_review_rules() -> List[ReviewRule]:
    items = _read_named_preference("review_rules")
    rules: List[ReviewRule] = []
    for key, payload in items.items():
        value = dict(payload.get("value", {}) or {})
        if not value:
            continue
        value.setdefault("id", key)
        value.setdefault("created_at", payload.get("created_at", ""))
        value.setdefault("updated_at", payload.get("updated_at", ""))
        try:
            rule = ReviewRule.from_dict(value)
        except Exception:
            continue
        if rule.id:
            rules.append(rule)
    return rules


def _serialize_review_rule(rule: ReviewRule) -> Dict[str, Any]:
    return rule.to_dict()


def _resolve_review_rule_payload(payload: ReviewRuleApplyRequest) -> ReviewRule:
    if payload.rule is not None:
        rule_id = str(payload.rule.id or uuid.uuid4().hex[:12]).strip()
        return ReviewRule.from_dict(
            {
                "id": rule_id,
                "name": payload.rule.name,
                "scope": payload.rule.scope,
                "description": payload.rule.description,
                "version": payload.rule.version,
                "conditions": payload.rule.conditions.model_dump(),
                "actions": payload.rule.actions.model_dump(),
            }
        )
    rule_id = str(payload.rule_id or "").strip()
    if not rule_id:
        raise HTTPException(status_code=400, detail="rule_id or rule is required")
    rule = next((item for item in _load_review_rules() if item.id == rule_id), None)
    if rule is None:
        raise HTTPException(status_code=404, detail="review rule not found")
    return rule


def _enrich_review_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    overlay_rows: Dict[str, Dict[str, Any]] | None = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    overlay_rows = overlay_rows or {}
    enriched_rows, collections = apply_collection_intelligence(rows)
    learned_rules = load_learned_rules(WORKSPACE_ROOT)
    raw_conflicts = _detect_manifest_conflicts(enriched_rows)
    conflict_row_ids = {str(item.get("row_id", "") or "") for item in raw_conflicts}
    final_rows: List[Dict[str, Any]] = []
    for index, row in enumerate(enriched_rows):
        row_id = str(row.get("row_id", index))
        suggestions = [item.to_dict() for item in suggest_for_row(row, learned_rules)]
        learned_suggestion_count = len(suggestions)
        collection_confidence = float(row.get("collection_confidence", 0.0) or 0.0)
        edited = row_id in overlay_rows
        has_conflict = row_id in conflict_row_ids
        bucket_decision = evaluate_review_bucket(
            row,
            conflict_open=has_conflict,
            edited=edited,
            collection_uncertain=collection_confidence < 0.85,
            learned_suggestion_count=learned_suggestion_count,
        )
        payload = dict(row)
        payload["row_id"] = row_id
        payload["has_conflict"] = has_conflict
        payload["edited"] = edited
        payload["review_bucket"] = bucket_decision.bucket
        payload["learned_suggestions"] = suggestions
        payload["review_explainability"] = {
            **bucket_decision.to_dict(),
            "collection_confidence": collection_confidence,
            "learned_suggestion_count": learned_suggestion_count,
            "edited": edited,
            "has_conflict": has_conflict,
        }
        final_rows.append(payload)
    queue_summary = build_review_queue_summary(final_rows).to_dict()
    collection_payload = [item.to_dict() for item in collections]
    copilot_summary = build_review_copilot_summary(final_rows, collection_payload).to_dict()
    return final_rows, queue_summary, collection_payload, copilot_summary


def _apply_overlay_rows(base_rows: Sequence[Dict[str, Any]], overlay_rows: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return apply_overlay_rows(base_rows, overlay_rows)


def _detect_manifest_conflicts(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return detect_manifest_conflicts(rows)


def _build_preview_payload(row: Dict[str, Any], row_id: str) -> Dict[str, Any]:
    return build_preview_payload(row, row_id)


def _get_manifest_path_for_job(record: JobRecord) -> Path:
    return get_manifest_path_for_job(record)


def _sse(event: str, payload: Dict[str, Any]) -> str:
    return sse(event, payload)


def _read_preference_items(path: Path) -> Dict[str, Dict[str, Any]]:
    return read_preference_items(_read_json_file, path)


def _write_preference_items(path: Path, items: Dict[str, Dict[str, Any]]) -> None:
    write_preference_items(_write_json_atomic, _now_iso, path, items)


def create_app(command_executor: CommandExecutor | None = None) -> FastAPI:
    app = FastAPI(title="Fileman Web API", version="2.0.0")
    router = APIRouter()

    _migrate_preference_roots()
    _bootstrap_runtime_defaults()

    WEB_JOB_ROOT.mkdir(parents=True, exist_ok=True)
    WEB_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    PREFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    ROLLBACK_ROOT.mkdir(parents=True, exist_ok=True)

    views_pref_name = "views"
    templates_pref_name = "naming_templates"
    review_rules_pref_name = "review_rules"

    store = JobStore(job_root=WEB_JOB_ROOT)
    runner = JobRunner(store=store, command_executor=command_executor)
    app.state.job_store = store
    app.state.job_runner = runner

    def new_analyze_artifacts() -> tuple[Path, Path, Path]:
        manifest_path = MANIFEST_ROOT / f"web-api-{uuid.uuid4().hex[:12]}.jsonl"
        csv_path = WEB_ARTIFACT_ROOT / "csv" / f"web-api-{uuid.uuid4().hex[:12]}.csv"
        report_path = REPORT_ROOT / f"web-api-{uuid.uuid4().hex[:12]}.json"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        return manifest_path, csv_path, report_path

    def new_apply_artifacts() -> tuple[Path, Path, Path]:
        out_manifest = MANIFEST_ROOT / f"web-apply-{uuid.uuid4().hex[:12]}.jsonl"
        report_path = REPORT_ROOT / f"web-apply-{uuid.uuid4().hex[:12]}.json"
        rollback_manifest = ROLLBACK_ROOT / f"web-rollback-{uuid.uuid4().hex[:12]}.jsonl"
        out_manifest.parent.mkdir(parents=True, exist_ok=True)
        return out_manifest, report_path, rollback_manifest

    def enqueue_job(kind: JobKind, payload: Dict[str, Any], retry_of: str | None = None) -> JobView:
        record = store.create(kind=kind, payload=payload, retry_of=retry_of)

        def worker(sink: EventSink) -> Dict[str, Any]:
            if kind == "analyze":
                watch_source_id = str(payload.get("watch_source_id", "") or "").strip()
                if watch_source_id or str(payload.get("trigger_source", "") or "").strip() == "inbox":
                    source_root = _resolve_watch_source_root(watch_source_id, field_name="source_dir")
                    source_dir = _resolve_internal_artifact_path(str(payload["source_dir"]), root=source_root, field_name="source_dir")
                    if not source_dir.exists() or not source_dir.is_dir():
                        raise HTTPException(status_code=400, detail="source_dir must exist")
                else:
                    source_dir = _resolve_controlled_input_directory(str(payload["source_dir"]), DEFAULT_INPUT_ROOT.resolve())
                manifest_path = _resolve_internal_artifact_path(
                    str(payload["manifest_path"]),
                    root=MANIFEST_ROOT,
                    field_name="manifest_path",
                )
                csv_path = _resolve_internal_artifact_path(
                    str(payload["csv_path"]),
                    root=WEB_ARTIFACT_ROOT,
                    field_name="csv_path",
                )
                report_path = _resolve_internal_artifact_path(
                    str(payload["report_path"]),
                    root=REPORT_ROOT,
                    field_name="report_path",
                )
                parsed_model = str(payload.get("model", "") or "").strip()
                parsed_categories = str(payload.get("categories", "") or "").strip()
                parsed_workers = int(payload.get("workers", 1) or 1)
                parsed_max_files = payload.get("max_files")
                parsed_max_total_mb = payload.get("max_total_mb")
                parsed_max_file_mb = payload.get("max_file_mb")
                parsed_offline = bool(payload.get("offline", False))
                mode = str(payload.get("input_mode", "directory") or "directory")

                command = _build_cli_command(
                    "analyze",
                    "--input",
                    str(source_dir),
                    "--manifest",
                    str(manifest_path),
                    "--csv",
                    str(csv_path),
                    "--report",
                    str(report_path),
                    "--workers",
                    str(max(parsed_workers, 1)),
                    run_id=record.id,
                )
                if parsed_model:
                    command.extend(["--model", parsed_model])
                if parsed_categories:
                    command.extend(["--categories", parsed_categories])
                if parsed_max_files is not None:
                    command.extend(["--max-files", str(parsed_max_files)])
                if parsed_max_total_mb is not None:
                    command.extend(["--max-total-mb", str(parsed_max_total_mb)])
                if parsed_max_file_mb is not None:
                    command.extend(["--max-file-mb", str(parsed_max_file_mb)])
                if parsed_offline:
                    command.append("--offline")

                sink.phase("analyze.start", 0.1)
                sink.info("analyze_input_ready", source_dir=str(source_dir), input_mode=mode)
                sink.check_cancelled()
                runner.run_command(command, cwd=REPO_ROOT, sink=sink)
                sink.check_cancelled()
                sink.phase("analyze.finalize", 0.95)

                analyze_report_payload: Dict[str, Any] = {}
                if report_path.exists():
                    analyze_report_payload = json.loads(
                        _resolve_existing_internal_file(report_path, root=REPORT_ROOT, field_name="report_path").read_text(encoding="utf-8")
                    )

                overlay_path = store.overlay_path(record.id)
                if not overlay_path.exists():
                    _save_overlay(overlay_path, record.id, {})
                    sink.info("manifest_overlay_initialized", overlay_path=str(overlay_path))

                return {
                    "manifest_path": str(manifest_path),
                    "report_path": str(report_path),
                    "csv_path": str(csv_path),
                    "overlay_path": str(overlay_path),
                    "input_mode": mode,
                    "input_root": str(source_dir),
                    "workers": max(parsed_workers, 1),
                    "categories": parsed_categories,
                    "total": int(analyze_report_payload.get("total", 0)),
                    "with_error": int(analyze_report_payload.get("with_error", 0)),
                }

            if kind == "apply":
                source_manifest_path = _resolve_manifest_path(store, None, str(payload["manifest_path"]))
                output_root = _resolve_controlled_output_directory(
                    str(payload["output_root"]),
                    DEFAULT_OUTPUT_ROOT.resolve(),
                )
                execute = bool(payload.get("execute", False))
                out_manifest = _resolve_internal_artifact_path(
                    str(payload["out_manifest_path"]),
                    root=MANIFEST_ROOT,
                    field_name="out_manifest_path",
                )
                report_path = _resolve_internal_artifact_path(
                    str(payload["report_path"]),
                    root=REPORT_ROOT,
                    field_name="report_path",
                )
                rollback_manifest = _resolve_internal_artifact_path(
                    str(payload["rollback_manifest_path"]),
                    root=ROLLBACK_ROOT,
                    field_name="rollback_manifest_path",
                )
                analyze_job_id = str(payload.get("analyze_job_id", "") or "").strip() or None
                input_root = _resolve_apply_input_root(store, analyze_job_id)

                sink.phase("apply.prepare_manifest", 0.1)
                sink.check_cancelled()
                base_rows = _read_manifest_rows(source_manifest_path)
                overlay_rows: Dict[str, Dict[str, Any]] = {}
                if analyze_job_id:
                    overlay_payload = _load_overlay(store.overlay_path(analyze_job_id), analyze_job_id)
                    overlay_rows = dict(overlay_payload.get("rows", {}) or {})
                resolved_rows = _apply_overlay_rows(base_rows, overlay_rows)
                resolved_manifest_path = store.job_dir(record.id) / "manifest_resolved.jsonl"
                _write_jsonl_rows(resolved_manifest_path, resolved_rows)
                sink.info(
                    "manifest_resolved_snapshot",
                    source_manifest_path=str(source_manifest_path),
                    resolved_manifest_path=str(resolved_manifest_path),
                    overlay_source_job_id=analyze_job_id or "",
                )
                sink.check_cancelled()

                command = _build_cli_command(
                    "apply",
                    "--manifest",
                    str(resolved_manifest_path),
                    "--output",
                    str(output_root),
                    "--out-manifest",
                    str(out_manifest),
                    "--report",
                    str(report_path),
                    "--rollback-manifest",
                    str(rollback_manifest),
                    "--input-root",
                    str(input_root),
                    "--verify-sha1",
                    run_id=record.id,
                )
                command.append("--no-dry-run" if execute else "--dry-run")

                sink.phase("apply.start", 0.3)
                sink.info("apply_mode", execute=execute)
                runner.run_command(command, cwd=REPO_ROOT, sink=sink)
                sink.check_cancelled()
                sink.phase("apply.finalize", 0.95)

                apply_report_payload: Dict[str, Any] = {}
                if report_path.exists():
                    apply_report_payload = json.loads(
                        _resolve_existing_internal_file(report_path, root=REPORT_ROOT, field_name="report_path").read_text(encoding="utf-8")
                    )
                return {
                    "manifest_path": str(out_manifest if out_manifest.exists() else source_manifest_path),
                    "source_manifest_path": str(source_manifest_path),
                    "resolved_manifest_path": str(resolved_manifest_path),
                    "report_path": str(report_path),
                    "rollback_manifest_path": str(rollback_manifest),
                    "dry_run": not execute,
                    "output_root": str(output_root),
                    "overlay_source_job_id": analyze_job_id,
                    "total": int(apply_report_payload.get("total", 0)),
                    "with_error": int(apply_report_payload.get("with_error", 0)),
                }

            manifest_path = _resolve_manifest_path(store, None, str(payload["manifest_path"]))
            execute = bool(payload.get("execute", False))
            allowed_root = str(payload.get("allowed_root", DEFAULT_ALLOWED_ROOT) or DEFAULT_ALLOWED_ROOT)
            strict_integrity = bool(payload.get("strict_integrity", True))

            command = _build_cli_command(
                "rollback",
                "--manifest",
                str(manifest_path),
                "--allowed-root",
                allowed_root,
                run_id=record.id,
            )
            command.append("--no-dry-run" if execute else "--dry-run")
            command.append("--strict-integrity" if strict_integrity else "--no-strict-integrity")

            sink.phase("rollback.start", 0.1)
            sink.info("rollback_mode", execute=execute)
            if not strict_integrity:
                sink.warn(
                    "rollback_integrity_relaxed",
                    strict_integrity=False,
                    hmac_key_present=_has_strong_rollback_signing_key(),
                    detail="strict_integrity=false; rollback signature verification is relaxed",
                )
            sink.check_cancelled()
            runner.run_command(command, cwd=REPO_ROOT, sink=sink)
            sink.check_cancelled()
            sink.phase("rollback.finalize", 0.95)
            return {
                "manifest_path": str(manifest_path),
                "dry_run": not execute,
                "allowed_root": allowed_root,
                "strict_integrity": strict_integrity,
                "source_job_id": str(payload.get("source_job_id", "") or "").strip(),
                "audit_reason": str(payload.get("audit_reason", "") or "").strip(),
            }

        runner.submit(record.id, worker)
        return _job_to_view(record)

    def build_retry_payload(source: JobRecord) -> Dict[str, Any]:
        payload = dict(source.payload)
        if source.kind == "analyze":
            manifest_path, csv_path, report_path = new_analyze_artifacts()
            payload.update(
                {
                    "manifest_path": str(manifest_path),
                    "csv_path": str(csv_path),
                    "report_path": str(report_path),
                }
            )
        elif source.kind == "apply":
            out_manifest, report_path, rollback_manifest = new_apply_artifacts()
            payload.update(
                {
                    "out_manifest_path": str(out_manifest),
                    "report_path": str(report_path),
                    "rollback_manifest_path": str(rollback_manifest),
                }
            )
        return payload

    def read_manifest_context(
        job_id: str,
    ) -> tuple[JobRecord, Path, List[Dict[str, Any]], Path, Dict[str, Any], Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        manifest_path = _get_manifest_path_for_job(record)
        base_rows = _read_manifest_rows(manifest_path)
        overlay_path = store.overlay_path(job_id)
        overlay_payload = _load_overlay(overlay_path, job_id)
        overlay_rows = dict(overlay_payload.get("rows", {}) or {})
        resolved_rows = _apply_overlay_rows(base_rows, overlay_rows)
        return record, manifest_path, base_rows, overlay_path, overlay_payload, overlay_rows, resolved_rows

    @router.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok", "service": "fileman-web-api"}

    @router.get("/api/jobs/history")
    def get_jobs_history(limit: int = Query(default=200, ge=1, le=2000)) -> Dict[str, Any]:
        items = [_job_to_view(item).model_dump() for item in store.list_history()[:limit]]
        return {
            "total": len(items),
            "items": items,
            "index_path": str(store.index_path),
        }

    @router.get("/api/jobs", response_model=List[JobView])
    def list_jobs() -> List[JobView]:
        return [_job_to_view(item) for item in store.list()]

    @router.get("/api/jobs/stream")
    async def stream_jobs(request: Request) -> StreamingResponse:
        async def event_stream() -> Any:
            last_fingerprint = ""
            initial_payload = {"jobs": [_job_to_view(item).model_dump() for item in store.list()]}
            last_fingerprint = json.dumps(initial_payload, ensure_ascii=False, sort_keys=True)
            yield _sse("snapshot", initial_payload)
            while True:
                if await request.is_disconnected():
                    break
                payload = {"jobs": [_job_to_view(item).model_dump() for item in store.list()]}
                fingerprint = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                if fingerprint != last_fingerprint:
                    last_fingerprint = fingerprint
                    yield _sse("jobs", payload)
                await asyncio.sleep(0.2)

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)

    @router.get("/api/jobs/{job_id}", response_model=JobView)
    def get_job(job_id: str) -> JobView:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return _job_to_view(record)

    @router.get("/api/jobs/{job_id}/events")
    def get_job_events(job_id: str) -> Dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "job_id": job_id,
            "events": [store._event_dict(event) for event in record.events],  # noqa: SLF001
        }

    @router.get("/api/jobs/{job_id}/stream")
    @router.get("/api/jobs/{job_id}/events/stream")
    async def stream_job_events(job_id: str, request: Request) -> StreamingResponse:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")

        async def event_stream() -> Any:
            cursor = 0
            snapshot = store.snapshot(job_id)
            if snapshot is not None:
                yield _sse("snapshot", snapshot)
            while True:
                if await request.is_disconnected():
                    break
                events, cursor, status = store.events_since(job_id, cursor)
                for event_payload in events:
                    yield _sse("event", event_payload)
                if status in TERMINAL_JOB_STATUSES and cursor >= store.event_count(job_id):
                    latest = store.snapshot(job_id) or {"id": job_id, "status": status}
                    yield _sse("done", latest)
                    break
                await asyncio.sleep(0.05)

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)

    @router.post("/api/jobs/{job_id}/cancel", response_model=JobView)
    def cancel_job(job_id: str) -> JobView:
        record = store.request_cancel(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return _job_to_view(record)

    @router.post("/api/jobs/{job_id}/retry", response_model=JobView, status_code=202)
    def retry_job(job_id: str) -> JobView:
        source = store.get(job_id)
        if source is None:
            raise HTTPException(status_code=404, detail="job not found")
        if source.status not in TERMINAL_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="only terminal jobs can be retried")
        payload = build_retry_payload(source)
        return enqueue_job(source.kind, payload, retry_of=source.id)

    @router.get("/api/jobs/{job_id}/manifest")
    def get_job_manifest(job_id: str, limit: int = Query(default=500, ge=1, le=5000)) -> Dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        manifest_path = _get_manifest_path_for_job(record)
        rows: List[Dict[str, Any]] = []
        for idx, row in enumerate(read_jsonl(manifest_path, validate=True)):
            if idx >= limit:
                break
            rows.append(dict(row))
        return {
            "job_id": job_id,
            "manifest_path": str(manifest_path),
            "rows": rows,
            "returned": len(rows),
            "limit": limit,
        }

    @router.get("/api/jobs/{job_id}/manifest/view")
    def get_manifest_view(job_id: str, limit: int = Query(default=500, ge=1, le=5000)) -> Dict[str, Any]:
        _, manifest_path, _, overlay_path, overlay_payload, overlay_rows, resolved_rows = read_manifest_context(job_id)
        review_rows, queue_summary, collections, copilot_summary = _enrich_review_rows(resolved_rows, overlay_rows=overlay_rows)
        rows: List[Dict[str, Any]] = []
        for idx, row in enumerate(review_rows):
            if idx >= limit:
                break
            payload = dict(row)
            payload["row_id"] = str(idx)
            rows.append(payload)
        return {
            "job_id": job_id,
            "manifest_path": str(manifest_path),
            "overlay_path": str(overlay_path),
            "overlay_updated_at": overlay_payload.get("updated_at"),
            "review_queue_summary": queue_summary,
            "collections": collections,
            "rows": rows,
            "returned": len(rows),
            "limit": limit,
        }

    @router.get("/api/jobs/{job_id}/manifest/{row_id}/preview")
    def get_manifest_preview(job_id: str, row_id: str) -> Dict[str, Any]:
        _, _, _, _, _, _, resolved_rows = read_manifest_context(job_id)
        index = _coerce_row_index(row_id, resolved_rows)
        return _build_preview_payload(resolved_rows[index], str(index))

    @router.patch("/api/jobs/{job_id}/manifest/rows/{row_id}")
    def patch_manifest_row(job_id: str, row_id: str, payload: ManifestRowPatchRequest) -> Dict[str, Any]:
        _, manifest_path, base_rows, overlay_path, overlay_payload, _, _ = read_manifest_context(job_id)
        index = _coerce_row_index(row_id, base_rows)
        patch = dict(payload.patch)
        if not patch:
            raise HTTPException(status_code=400, detail="patch cannot be empty")
        allowed_fields = set(base_rows[index].keys()) | MANIFEST_EDITABLE_EXTRA_FIELDS
        invalid_fields = [patch_field for patch_field in patch if patch_field not in allowed_fields]
        if invalid_fields:
            raise HTTPException(status_code=400, detail=f"invalid patch fields: {', '.join(sorted(invalid_fields))}")

        overlay_rows = dict(overlay_payload.get("rows", {}) or {})
        row_key = str(index)
        row_patch = dict(overlay_rows.get(row_key, {}) or {})
        for patch_key, value in patch.items():
            row_patch[patch_key] = value
        overlay_rows[row_key] = row_patch
        saved_overlay = _save_overlay(overlay_path, job_id, overlay_rows)
        store.add_event(job_id, "info", "manifest_overlay_row_patched", row_id=row_key, patch=patch)

        resolved_rows = _apply_overlay_rows(base_rows, overlay_rows)
        updated_row = dict(resolved_rows[index])
        updated_row["row_id"] = row_key
        return {
            "job_id": job_id,
            "manifest_path": str(manifest_path),
            "overlay_path": str(overlay_path),
            "overlay_updated_at": saved_overlay.get("updated_at"),
            "row": updated_row,
        }

    @router.post("/api/jobs/{job_id}/manifest/batch")
    def patch_manifest_batch(job_id: str, payload: ManifestBatchRequest) -> Dict[str, Any]:
        _, manifest_path, base_rows, overlay_path, overlay_payload, _, _ = read_manifest_context(job_id)
        if not payload.operations:
            raise HTTPException(status_code=400, detail="operations cannot be empty")

        overlay_rows = dict(overlay_payload.get("rows", {}) or {})
        for operation in payload.operations:
            index = _coerce_row_index(operation.row_id, base_rows)
            patch = dict(operation.patch)
            if not patch:
                continue
            allowed_fields = set(base_rows[index].keys()) | MANIFEST_EDITABLE_EXTRA_FIELDS
            invalid_fields = [patch_field for patch_field in patch if patch_field not in allowed_fields]
            if invalid_fields:
                raise HTTPException(status_code=400, detail=f"invalid patch fields: {', '.join(sorted(invalid_fields))}")
            row_key = str(index)
            row_patch = dict(overlay_rows.get(row_key, {}) or {})
            row_patch.update(patch)
            overlay_rows[row_key] = row_patch

        saved_overlay = _save_overlay(overlay_path, job_id, overlay_rows)
        store.add_event(job_id, "info", "manifest_overlay_batch_patched", count=len(payload.operations))

        resolved_rows = _apply_overlay_rows(base_rows, overlay_rows)
        learned_rules = learn_category_rules(base_rows, resolved_rows, updated_at=_now_iso())
        if learned_rules:
            save_learned_rules(WORKSPACE_ROOT, learned_rules, updated_at=_now_iso())
        review_rows, queue_summary, collections, copilot_summary = _enrich_review_rows(resolved_rows, overlay_rows=overlay_rows)
        return {
            "job_id": job_id,
            "manifest_path": str(manifest_path),
            "overlay_path": str(overlay_path),
            "overlay_updated_at": saved_overlay.get("updated_at"),
            "rows": [dict(row, row_id=str(idx)) for idx, row in enumerate(resolved_rows)],
            "returned": len(resolved_rows),
            "review_queue_summary": queue_summary,
            "collections": collections,
            "copilot_summary": copilot_summary,
        }

    @router.get("/api/jobs/{job_id}/manifest/conflicts")
    def get_manifest_conflicts(job_id: str) -> Dict[str, Any]:
        _, manifest_path, _, _, _, _, resolved_rows = read_manifest_context(job_id)
        conflicts = _detect_manifest_conflicts(resolved_rows)
        return {
            "job_id": job_id,
            "manifest_path": str(manifest_path),
            "conflicts": conflicts,
            "count": len(conflicts),
        }

    @router.post("/api/jobs/{job_id}/manifest/conflicts/resolve")
    def resolve_manifest_conflicts(job_id: str, payload: ManifestConflictResolveRequest) -> Dict[str, Any]:
        _, manifest_path, base_rows, overlay_path, overlay_payload, _, _ = read_manifest_context(job_id)
        if not payload.resolutions:
            raise HTTPException(status_code=400, detail="resolutions cannot be empty")
        overlay_rows = dict(overlay_payload.get("rows", {}) or {})

        for resolution in payload.resolutions:
            index = _coerce_row_index(resolution.row_id, base_rows)
            row_key = str(index)
            row_patch = dict(overlay_rows.get(row_key, {}) or {})
            row_patch["new_path"] = resolution.new_path
            overlay_rows[row_key] = row_patch

        saved_overlay = _save_overlay(overlay_path, job_id, overlay_rows)
        store.add_event(job_id, "info", "manifest_conflicts_resolved", count=len(payload.resolutions))

        resolved_rows = _apply_overlay_rows(base_rows, overlay_rows)
        learned_rules = learn_category_rules(base_rows, resolved_rows, updated_at=_now_iso())
        if learned_rules:
            save_learned_rules(WORKSPACE_ROOT, learned_rules, updated_at=_now_iso())
        conflicts = _detect_manifest_conflicts(resolved_rows)
        return {
            "job_id": job_id,
            "manifest_path": str(manifest_path),
            "overlay_path": str(overlay_path),
            "overlay_updated_at": saved_overlay.get("updated_at"),
            "remaining_conflicts": conflicts,
            "remaining_count": len(conflicts),
        }

    @router.get("/api/jobs/{job_id}/review-queue")
    def get_review_queue(job_id: str, limit: int = Query(default=500, ge=1, le=5000)) -> Dict[str, Any]:
        record, manifest_path, _, overlay_path, overlay_payload, overlay_rows, resolved_rows = read_manifest_context(job_id)
        review_rows, queue_summary, collections, copilot_summary = _enrich_review_rows(resolved_rows, overlay_rows=overlay_rows)
        return {
            "job": _job_to_view(record).model_dump(),
            "job_id": job_id,
            "manifest_path": str(manifest_path),
            "overlay_path": str(overlay_path),
            "overlay_updated_at": overlay_payload.get("updated_at"),
            "summary": queue_summary,
            "copilot_summary": copilot_summary,
            "collections": collections,
            "rows": review_rows[:limit],
            "returned": min(limit, len(review_rows)),
        }

    @router.get("/api/jobs/{job_id}/report")
    def get_job_report(job_id: str) -> Dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        report_path = str(record.summary.get("report_path", "")).strip()
        if not report_path:
            raise HTTPException(status_code=409, detail="job has no report output")
        target = _resolve_existing_internal_file(report_path, root=REPORT_ROOT, field_name="report_path")
        report_payload = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(report_payload, dict):
            _, _, _, _, _, overlay_rows, resolved_rows = read_manifest_context(job_id)
            review_rows, queue_summary, collections, copilot_summary = _enrich_review_rows(resolved_rows, overlay_rows=overlay_rows)
            learned_rules = load_learned_rules(WORKSPACE_ROOT)
            report_payload.setdefault("by_review_bucket", queue_summary)
            report_payload.setdefault("collection_count", len(collections))
            report_payload.setdefault("collection_ids", [item["id"] for item in collections])
            report_payload.setdefault("collection_summaries", collections)
            report_payload.setdefault("rows_with_learning_suggestions", sum(1 for row in review_rows if row.get("learned_suggestions")))
            report_payload.setdefault("learned_rule_count", len(learned_rules))
            report_payload.setdefault(
                "reusable_learning_rule_count",
                sum(1 for rule in learned_rules if str(getattr(rule, "reuse_scope", "")).strip() == "reusable"),
            )
            report_payload.setdefault("review_copilot_summary", copilot_summary)
            report_payload.setdefault("review_bridge", _build_report_review_bridge(job_id, queue_summary, collections, copilot_summary))
        return {"job_id": job_id, "report_path": str(target), "report": report_payload}

    @router.get("/api/jobs/{job_id}/audit")
    def get_job_audit(job_id: str, tail: int = Query(default=200, ge=1, le=5000)) -> Dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        job_dir = store.job_dir(job_id)
        overlay_path = store.overlay_path(job_id)
        events = [store._event_dict(event) for event in record.events[-tail:]]  # noqa: SLF001
        return {
            "job": _job_to_view(record).model_dump(),
            "payload": record.payload,
            "summary": record.summary,
            "event_count": len(record.events),
            "events_tail": events,
            "paths": {
                "job_dir": str(job_dir),
                "job_json_path": str(store.job_file(job_id)),
                "events_jsonl_path": str(store.events_file(job_id)),
                "overlay_path": str(overlay_path),
                "index_path": str(store.index_path),
            },
        }

    @router.post("/api/jobs/analyze", response_model=JobView, status_code=202)
    async def create_analyze_job(
        request: Request,
        files: List[UploadFile] = File(default_factory=list),
        relative_paths: List[str] = Form(default_factory=list),
        input_mode: str | None = Form(default=None),
        input_directory: str | None = Form(default=None),
        strategy_pack_id: str | None = Form(default=None),
        watch_source_id: str | None = Form(default=None),
        trigger_source: str | None = Form(default=None),
        model: str | None = Form(default=None),
        categories: str | None = Form(default=None),
        workers: str | None = Form(default=None),
        max_files: str | None = Form(default=None),
        max_total_mb: str | None = Form(default=None),
        max_file_mb: str | None = Form(default=None),
        offline: str | None = Form(default=None),
    ) -> JobView:
        parsed_mode = input_mode
        parsed_input_directory = input_directory
        parsed_strategy_pack_id = strategy_pack_id
        parsed_watch_source_id = watch_source_id
        parsed_trigger_source = trigger_source
        parsed_model = model
        parsed_categories = categories
        parsed_workers = _parse_form_int(workers, "workers")
        parsed_max_files = _parse_form_int(max_files, "max_files")
        parsed_max_total_mb = _parse_form_float(max_total_mb, "max_total_mb")
        parsed_max_file_mb = _parse_form_float(max_file_mb, "max_file_mb")
        parsed_offline = _parse_form_bool(offline, default=False)
        runtime_settings = _runtime_settings_view()
        runtime_defaults = runtime_settings.analyze_defaults.model_dump()

        content_type = request.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            analyze_payload = AnalyzeJsonRequest.model_validate(await request.json())
            parsed_mode = analyze_payload.input_mode
            parsed_input_directory = analyze_payload.input_directory
            parsed_strategy_pack_id = analyze_payload.strategy_pack_id
            parsed_watch_source_id = analyze_payload.watch_source_id
            parsed_trigger_source = analyze_payload.trigger_source
            parsed_model = analyze_payload.model
            parsed_categories = analyze_payload.categories
            parsed_workers = analyze_payload.workers
            parsed_max_files = analyze_payload.max_files
            parsed_max_total_mb = analyze_payload.max_total_mb
            parsed_max_file_mb = analyze_payload.max_file_mb
            parsed_offline = analyze_payload.offline
        elif parsed_mode is None:
            parsed_mode = "upload" if files else "directory"

        mode = str(parsed_mode or "directory").strip().lower()
        if mode not in {"directory", "upload"}:
            raise HTTPException(status_code=400, detail="input_mode must be 'directory' or 'upload'")

        effective_input_directory = str(parsed_input_directory or runtime_settings.input_root).strip()

        if mode == "directory":
            source_dir = _resolve_controlled_input_directory(
                effective_input_directory,
                Path(runtime_settings.input_root),
            )
        else:
            if not files:
                raise HTTPException(status_code=400, detail="upload mode requires at least one file")
            upload_dir = WEB_UPLOAD_ROOT / f"upload-{uuid.uuid4().hex[:10]}"
            upload_dir.mkdir(parents=True, exist_ok=True)
            for idx, upload in enumerate(files, start=1):
                relative_path = relative_paths[idx - 1] if idx - 1 < len(relative_paths) else ""
                relative_target = _sanitize_relative_upload_path(relative_path, upload.filename or "", idx)
                target = upload_dir / relative_target
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as handle:
                    while True:
                        chunk = await upload.read(UPLOAD_COPY_CHUNK_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                await upload.close()
            source_dir = upload_dir.resolve()

        enqueue_payload, _ = _build_analyze_enqueue_payload(
            source_dir,
            artifacts_factory=new_analyze_artifacts,
            runtime_settings=runtime_settings,
            runtime_defaults=runtime_defaults,
            strategy_pack_id=parsed_strategy_pack_id,
            watch_source_id=parsed_watch_source_id,
            trigger_source=str(parsed_trigger_source or "manual").strip() or "manual",
            model=parsed_model,
            categories=parsed_categories,
            workers=parsed_workers,
            max_files=parsed_max_files,
            max_total_mb=parsed_max_total_mb,
            max_file_mb=parsed_max_file_mb,
            offline=bool(parsed_offline),
        )
        enqueue_payload["input_mode"] = mode
        return enqueue_job("analyze", enqueue_payload)

    @router.get("/api/preferences/runtime", response_model=RuntimeSettingsView)
    def get_runtime_settings() -> RuntimeSettingsView:
        return _runtime_settings_view()

    @router.post("/api/preferences/runtime", response_model=RuntimeSettingsView)
    def upsert_runtime_settings(payload: RuntimeSettingsUpdateRequest) -> RuntimeSettingsView:
        return _update_runtime_settings(payload)

    @router.post("/api/preferences/runtime/validate", response_model=RuntimeSettingsView)
    def validate_runtime_settings() -> RuntimeSettingsView:
        return _runtime_settings_view()

    @router.post("/api/jobs/apply", response_model=JobView, status_code=202)
    def create_apply_job(payload: ApplyRequest) -> JobView:
        manifest_path = _resolve_manifest_path(store, payload.analyze_job_id, payload.manifest_path)
        execute = bool(payload.execute)
        if execute and not store.has_dry_run_success(manifest_path):
            raise HTTPException(status_code=409, detail="apply execute requires a successful dry-run for the same manifest")

        output_root = _resolve_controlled_output_directory(payload.output_root, DEFAULT_OUTPUT_ROOT.resolve())
        out_manifest, report_path, rollback_manifest = new_apply_artifacts()
        job_payload = {
            "manifest_path": str(manifest_path),
            "analyze_job_id": payload.analyze_job_id,
            "output_root": str(output_root),
            "execute": execute,
            "out_manifest_path": str(out_manifest),
            "report_path": str(report_path),
            "rollback_manifest_path": str(rollback_manifest),
        }
        return enqueue_job("apply", job_payload)

    @router.post("/api/jobs/rollback", response_model=JobView, status_code=202)
    def create_rollback_job(payload: RollbackRequest) -> JobView:
        manifest_path = _resolve_manifest_path(store, payload.analyze_job_id, payload.manifest_path)
        _validate_manifest_for_rollback(manifest_path)
        execute = bool(payload.execute)
        strict_integrity = bool(payload.strict_integrity)
        if strict_integrity and not _has_strong_rollback_signing_key():
            raise HTTPException(status_code=400, detail="strict_integrity=true requires FILEMAN_ROLLBACK_HMAC_KEY")
        job_payload = {
            "manifest_path": str(manifest_path),
            "execute": execute,
            "allowed_root": str(payload.allowed_root or DEFAULT_ALLOWED_ROOT),
            "strict_integrity": strict_integrity,
            "source_job_id": str(payload.source_job_id or payload.analyze_job_id or "").strip(),
            "audit_reason": str(payload.audit_reason or "").strip(),
        }
        return enqueue_job("rollback", job_payload)

    @router.get("/api/preferences/views")
    def list_saved_views() -> Dict[str, Any]:
        items_map = _read_named_preference(views_pref_name)
        items = [{"key": key, **value} for key, value in sorted(items_map.items())]
        return {"items": items, "count": len(items), "path": str(_preference_root() / "views.json")}

    @router.post("/api/preferences/views")
    def upsert_saved_view(payload: PreferenceUpsertRequest) -> Dict[str, Any]:
        items = _read_named_preference(views_pref_name)
        now = _now_iso()
        current = dict(items.get(payload.key, {}) or {})
        items[payload.key] = {
            "value": payload.value,
            "created_at": current.get("created_at", now),
            "updated_at": now,
        }
        _write_named_preference(views_pref_name, items)
        return {"key": payload.key, **items[payload.key]}

    @router.delete("/api/preferences/views")
    def delete_saved_view(key: str = Query(..., min_length=1)) -> Dict[str, Any]:
        items = _read_named_preference(views_pref_name)
        if key not in items:
            raise HTTPException(status_code=404, detail="view not found")
        removed = items.pop(key)
        _write_named_preference(views_pref_name, items)
        return {"deleted": True, "key": key, "value": removed}

    @router.get("/api/preferences/naming-templates")
    def list_naming_templates() -> Dict[str, Any]:
        items_map = _read_named_preference(templates_pref_name)
        items = [{"key": key, **value} for key, value in sorted(items_map.items())]
        return {"items": items, "count": len(items), "path": str(_preference_root() / "naming_templates.json")}

    @router.post("/api/preferences/naming-templates")
    def upsert_naming_template(payload: PreferenceUpsertRequest) -> Dict[str, Any]:
        items = _read_named_preference(templates_pref_name)
        now = _now_iso()
        current = dict(items.get(payload.key, {}) or {})
        items[payload.key] = {
            "value": payload.value,
            "created_at": current.get("created_at", now),
            "updated_at": now,
        }
        _write_named_preference(templates_pref_name, items)
        return {"key": payload.key, **items[payload.key]}

    @router.delete("/api/preferences/naming-templates")
    def delete_naming_template(key: str = Query(..., min_length=1)) -> Dict[str, Any]:
        items = _read_named_preference(templates_pref_name)
        if key not in items:
            raise HTTPException(status_code=404, detail="template not found")
        removed = items.pop(key)
        _write_named_preference(templates_pref_name, items)
        return {"deleted": True, "key": key, "value": removed}

    @router.get("/api/preferences/review-rules")
    def list_review_rules() -> Dict[str, Any]:
        rules = [_serialize_review_rule(rule) for rule in _load_review_rules()]
        return {"items": rules, "count": len(rules), "path": str(_preference_root() / "review_rules.json")}

    @router.post("/api/preferences/review-rules")
    def upsert_review_rule(payload: ReviewRuleUpsertRequest) -> Dict[str, Any]:
        rules = _read_named_preference(review_rules_pref_name)
        now = _now_iso()
        rule_id = str(payload.id or uuid.uuid4().hex[:12]).strip()
        rules[rule_id] = {
            "value": {
                "id": rule_id,
                "name": payload.name,
                "scope": payload.scope,
                "description": payload.description,
                "version": payload.version,
                "conditions": payload.conditions.model_dump(),
                "actions": payload.actions.model_dump(),
            },
            "created_at": dict(rules.get(rule_id, {}) or {}).get("created_at", now),
            "updated_at": now,
        }
        _write_named_preference(review_rules_pref_name, rules)
        return {"id": rule_id, **rules[rule_id]["value"], "created_at": rules[rule_id]["created_at"], "updated_at": now}

    @router.delete("/api/preferences/review-rules")
    def delete_review_rule(key: str = Query(..., min_length=1)) -> Dict[str, Any]:
        items = _read_named_preference(review_rules_pref_name)
        if key not in items:
            raise HTTPException(status_code=404, detail="review rule not found")
        removed = items.pop(key)
        _write_named_preference(review_rules_pref_name, items)
        return {"deleted": True, "key": key, "value": removed}

    @router.post("/api/jobs/{job_id}/review-rules/preview")
    def preview_review_rule(job_id: str, payload: ReviewRuleApplyRequest) -> Dict[str, Any]:
        _, _, _, _, _, overlay_rows, resolved_rows = read_manifest_context(job_id)
        review_rows, _, _, _ = _enrich_review_rows(resolved_rows, overlay_rows=overlay_rows)
        rule = _resolve_review_rule_payload(payload)
        preview = preview_rules(rule, review_rows)
        return {"job_id": job_id, "rule": rule.to_dict(), **preview}

    @router.post("/api/jobs/{job_id}/review-rules/apply")
    def apply_review_rule(job_id: str, payload: ReviewRuleApplyRequest) -> Dict[str, Any]:
        _, manifest_path, base_rows, overlay_path, overlay_payload, overlay_rows, resolved_rows = read_manifest_context(job_id)
        review_rows, _, _, _ = _enrich_review_rows(resolved_rows, overlay_rows=overlay_rows)
        rule = _resolve_review_rule_payload(payload)
        generated_overlay = apply_rule_to_overlay(rule, review_rows)
        next_overlay_rows = dict(overlay_rows)
        for row_id, patch in generated_overlay.items():
            current_patch = dict(next_overlay_rows.get(row_id, {}) or {})
            current_patch.update(patch)
            next_overlay_rows[row_id] = current_patch
        saved_overlay = _save_overlay(overlay_path, job_id, next_overlay_rows)
        resolved_after = _apply_overlay_rows(base_rows, next_overlay_rows)
        learned_rules = learn_category_rules(base_rows, resolved_after, updated_at=_now_iso())
        if learned_rules:
            save_learned_rules(WORKSPACE_ROOT, learned_rules, updated_at=_now_iso())
        review_rows_after, queue_summary, collections, copilot_summary = _enrich_review_rows(resolved_after, overlay_rows=next_overlay_rows)
        return {
            "job_id": job_id,
            "manifest_path": str(manifest_path),
            "overlay_path": str(overlay_path),
            "overlay_updated_at": saved_overlay.get("updated_at"),
            "applied_rule_id": rule.id,
            "matched_count": len(generated_overlay),
            "mode": "overlay_only",
            "execute_allowed": False,
            "summary": queue_summary,
            "copilot_summary": copilot_summary,
            "collections": collections,
            "rows": review_rows_after,
        }

    @router.post("/api/jobs/{job_id}/review-rules/from-examples")
    def draft_review_rule_from_examples(job_id: str, payload: ReviewRuleFromExamplesRequest) -> Dict[str, Any]:
        _, _, _, _, _, overlay_rows, resolved_rows = read_manifest_context(job_id)
        review_rows, _, _, _ = _enrich_review_rows(resolved_rows, overlay_rows=overlay_rows)
        selected_ids = {str(item) for item in payload.row_ids}
        selected_rows = [row for row in review_rows if str(row.get("row_id", row.get("id", "")) or "") in selected_ids]
        if len(selected_rows) != len(selected_ids):
            raise HTTPException(status_code=404, detail="one or more example rows were not found in the review queue")
        try:
            draft = build_rule_draft_from_examples(selected_rows, name=payload.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "job_id": job_id,
            "selected_count": len(selected_rows),
            "selected_row_ids": [str(row.get("row_id", row.get("id", "")) or "") for row in selected_rows],
            "mode": "draft_only",
            "save_allowed": False,
            "apply_allowed": False,
            "execute_allowed": False,
            "draft": draft,
            "warnings": draft.get("warnings", []),
        }

    @router.post("/api/jobs/{job_id}/review-queue/batch-triage")
    def batch_triage_review_queue(job_id: str, payload: ReviewQueueBatchTriageRequest) -> Dict[str, Any]:
        if payload.set_category is None and payload.set_ignore is None:
            raise HTTPException(status_code=400, detail="at least one batch triage action is required")

        _, manifest_path, base_rows, overlay_path, overlay_payload, overlay_rows, resolved_rows = read_manifest_context(job_id)
        review_rows, _, _, _ = _enrich_review_rows(resolved_rows, overlay_rows=overlay_rows)
        selected_ids = {str(item) for item in payload.row_ids}
        selected_rows = [row for row in review_rows if str(row.get("row_id", row.get("id", "")) or "") in selected_ids]
        if len(selected_rows) != len(selected_ids):
            raise HTTPException(status_code=404, detail="one or more selected rows were not found in the review queue")

        next_overlay_rows = dict(overlay_rows)
        for row in selected_rows:
            row_key = str(row.get("row_id", row.get("id", "")) or "")
            current_patch = dict(next_overlay_rows.get(row_key, {}) or {})
            current_ai_patch = dict(current_patch.get("ai", {}) or {})
            if payload.set_category is not None:
                current_ai_patch["category"] = payload.set_category
            if payload.set_ignore is not None:
                current_patch["ignore"] = payload.set_ignore
            if current_ai_patch:
                current_patch["ai"] = current_ai_patch
            next_overlay_rows[row_key] = current_patch

        saved_overlay = _save_overlay(overlay_path, job_id, next_overlay_rows)
        store.add_event(
            job_id,
            "info",
            "review_queue_batch_triaged",
            count=len(selected_rows),
            set_category=payload.set_category or "",
            set_ignore=payload.set_ignore,
        )
        resolved_after = _apply_overlay_rows(base_rows, next_overlay_rows)
        learned_rules = learn_category_rules(base_rows, resolved_after, updated_at=_now_iso())
        if learned_rules:
            save_learned_rules(WORKSPACE_ROOT, learned_rules, updated_at=_now_iso())
        review_rows_after, queue_summary, collections, copilot_summary = _enrich_review_rows(resolved_after, overlay_rows=next_overlay_rows)
        return {
            "job_id": job_id,
            "manifest_path": str(manifest_path),
            "overlay_path": str(overlay_path),
            "overlay_updated_at": saved_overlay.get("updated_at"),
            "mode": "overlay_only",
            "execute_allowed": False,
            "summary": queue_summary,
            "copilot_summary": copilot_summary,
            "collections": collections,
            "rows": review_rows_after,
            "applied_count": len(selected_rows),
        }

    @router.get("/api/preferences/strategy-packs")
    def list_strategy_packs() -> Dict[str, Any]:
        items = list_strategy_pack_payloads(REPO_ROOT)
        active_pack_id = get_active_strategy_pack_id(WORKSPACE_ROOT)
        active_pack = next((item for item in items if str(item.get("id", "") or "") == active_pack_id), None)
        return {"items": items, "count": len(items), "active_strategy_pack_id": active_pack_id, "active_pack": active_pack}

    @router.get("/api/preferences/learned-rules")
    def list_learned_rules() -> Dict[str, Any]:
        rules = [rule.to_dict() for rule in load_learned_rules(WORKSPACE_ROOT)]
        return {
            "items": rules,
            "count": len(rules),
            "path": str(WORKSPACE_ROOT / ".fileman" / "preferences" / "learned_rules.json"),
        }

    @router.delete("/api/preferences/learned-rules")
    def reset_learned_rules() -> Dict[str, Any]:
        save_learned_rules(WORKSPACE_ROOT, [], updated_at=_now_iso())
        return {"deleted": True}

    @router.get("/api/preferences/watch-sources")
    def list_watch_sources_route() -> Dict[str, Any]:
        pack_index = {str(item.get("id", "") or ""): item for item in list_strategy_pack_payloads(REPO_ROOT)}
        items = []
        for source in load_watch_sources(WORKSPACE_ROOT):
            payload = source.to_dict()
            payload["strategy_pack"] = pack_index.get(source.strategy_pack_id)
            items.append(payload)
        return {"items": items, "count": len(items), "path": str(WORKSPACE_ROOT / ".fileman" / "preferences" / "watch_sources.json")}

    @router.post("/api/preferences/watch-sources")
    def upsert_watch_source(payload: WatchSourceUpsertRequest) -> Dict[str, Any]:
        sources = load_watch_sources(WORKSPACE_ROOT)
        source_id = str(payload.id or uuid.uuid4().hex[:12]).strip()
        now = _now_iso()
        normalized_input_root = _normalize_operator_directory_input(payload.input_root, field_name="input_root")
        next_sources = [source for source in sources if source.id != source_id]
        current = next((source for source in sources if source.id == source_id), None)
        next_sources.append(
            WatchSource(
                id=source_id,
                name=payload.name,
                input_root=str(normalized_input_root),
                enabled=payload.enabled,
                strategy_pack_id=payload.strategy_pack_id,
                created_at=current.created_at if current is not None else now,
                updated_at=now,
            )
        )
        save_watch_sources(WORKSPACE_ROOT, sorted(next_sources, key=lambda item: item.name.lower()), updated_at=now)
        return next(item.to_dict() for item in next_sources if item.id == source_id)

    @router.delete("/api/preferences/watch-sources")
    def delete_watch_source(key: str = Query(..., min_length=1)) -> Dict[str, Any]:
        sources = load_watch_sources(WORKSPACE_ROOT)
        next_sources = [source for source in sources if source.id != key]
        if len(next_sources) == len(sources):
            raise HTTPException(status_code=404, detail="watch source not found")
        save_watch_sources(WORKSPACE_ROOT, next_sources, updated_at=_now_iso())
        return {"deleted": True, "key": key}

    @router.post("/api/inbox/scan")
    def scan_inbox_sources() -> Dict[str, Any]:
        runtime_settings = _runtime_settings_view()
        batches = []
        for batch in scan_watch_sources_once(load_watch_sources(WORKSPACE_ROOT)):
            source = WatchSource(
                id=batch.watch_source_id,
                name=batch.source_name,
                input_root=batch.input_root,
                enabled=True,
                strategy_pack_id=batch.strategy_pack_id,
            )
            batches.append(_build_inbox_batch_view(batch, source, runtime_settings))
        return {"items": batches, "count": len(batches), "mode": "discovery_only", "analyze_route": "/api/inbox/analyze"}

    @router.post("/api/inbox/analyze", status_code=202)
    def start_inbox_analyze(payload: InboxAnalyzeRequest) -> Dict[str, Any]:
        runtime_settings = _runtime_settings_view()
        runtime_defaults = runtime_settings.analyze_defaults.model_dump()
        source = next((item for item in load_watch_sources(WORKSPACE_ROOT) if item.id == payload.watch_source_id), None)
        if source is None:
            raise HTTPException(status_code=404, detail="watch source not found")
        source_root = _resolve_existing_operator_directory(source.input_root, field_name="watch source input root")
        batch = next((item for item in scan_watch_sources_once([source])), None)
        if batch is None:
            raise HTTPException(status_code=409, detail="watch source has no discovered files to analyze")
        if payload.batch_id and payload.batch_id != batch.id:
            raise HTTPException(status_code=409, detail="inbox batch changed since the last scan; rescan before analyzing")
        enqueue_payload, pack_payload = _build_analyze_enqueue_payload(
            source_root,
            artifacts_factory=new_analyze_artifacts,
            runtime_settings=runtime_settings,
            runtime_defaults=runtime_defaults,
            strategy_pack_id=payload.strategy_pack_id or source.strategy_pack_id or get_active_strategy_pack_id(WORKSPACE_ROOT),
            watch_source_id=source.id,
            trigger_source="inbox",
            model=payload.model,
            categories=payload.categories,
            workers=payload.workers,
            max_files=payload.max_files,
            max_total_mb=payload.max_total_mb,
            max_file_mb=payload.max_file_mb,
            offline=payload.offline,
        )
        job_view = enqueue_job("analyze", enqueue_payload)
        batch_payload = _build_inbox_batch_view(batch, source, runtime_settings)
        batch_payload["analyze_job_id"] = job_view.id
        return {
            "job": job_view.model_dump(),
            "job_id": job_view.id,
            "mode": "explicit_inbox_action",
            "batch": batch_payload,
            "strategy_pack": pack_payload,
            "review_next": {
                "review_queue_path": f"/api/jobs/{job_view.id}/review-queue",
                "report_path": f"/api/jobs/{job_view.id}/report",
                "execute_allowed": False,
            },
        }

    app.include_router(router)

    frontend_dist = FRONTEND_DIST_ROOT
    if frontend_dist.exists():
        asset_dir = frontend_dist / "assets"
        if asset_dir.exists():
            app.mount("/app/assets", StaticFiles(directory=str(asset_dir)), name="ui_assets")
            app.mount("/assets", StaticFiles(directory=str(asset_dir)), name="ui_assets_root")

        @app.get("/app")
        @app.get("/app/")
        def serve_ui_index() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

        @app.get("/app/{path:path}")
        def serve_ui_path(path: str) -> FileResponse:
            candidate = _resolve_root_descendant_path(path, root=frontend_dist, field_name="frontend_asset")
            if candidate.exists() and candidate.is_file() and _within_root(candidate, frontend_dist):
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    else:

        @app.get("/app")
        @app.get("/app/")
        def ui_placeholder() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Frontend static assets not found.",
                    "expected_dist": str(frontend_dist),
                    "hint": "Build webui and serve from /app when dist is available.",
                },
            )

    return app


app = create_app()
