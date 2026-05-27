# Logging And Observability Policy (No Logs No Merge)

## 1. Goal

- Structured logs must remain diagnosable, correlated, and safe to publish.
- Any critical-path change that does not update its logging design and verification must fail closed before merge.

## 2. Scope (Critical Paths)

- Business flows: `analyze`, `apply`, `rollback`, `report`
- Entry flows: CLI argument parsing, config loading, manifest read/write
- File actions: rename, move, rollback, conflict handling, retry paths
- External calls: AI/network requests, third-party APIs, timeout/retry paths

## 3. Minimum Structured Log Fields

Every critical-path log event must include at least these fields:

| Field | Meaning |
| --- | --- |
| `timestamp` | ISO8601 timestamp |
| `level` | `DEBUG/INFO/WARN/ERROR` |
| `event` | Verb-style event name such as `manifest.load.start` |
| `trace_id` | End-to-end correlation ID for the same request/task |
| `module` | Module name such as `packages.application.apply_command` |
| `action` | Current action such as `move_file` |
| `status` | `success/fail/retry/skipped` |
| `duration_ms` | Action duration in milliseconds |

Current implementation conventions:

- `packages.observability.logging_utils.log_event()` auto-populates `trace_id/module/action/status/request_id/session_id/user_id`.
- Legacy callers may still pass `run_id`; it is normalized into `trace_id/request_id/session_id`.
- `duration_s` is normalized to `duration_ms`.
- The terminal event contract lives in `contracts/runtime/event_schema.yaml`; the current implementation also fills `run_id/span_id/service/component/failure_domain/workspace_id`.
- Runtime governance commands must also tag which cleanup rail they are touching so cache trimming, docker pruning, and receipt retention all remain distinguishable in post-run evidence.

Required context fields for critical paths:

| Field | Meaning |
| --- | --- |
| `user_id` | Anonymized user identity |
| `session_id` | Session identifier; reuse trace when no session exists |
| `request_id` | Request identifier; CLI may reuse trace |
| `manifest_id` | Manifest filename or ID |
| `target_path` | Target path, redacted when needed |
| `bucket` | Cleanup or audit rail such as `repo_local`, `machine_cache`, `workspace_evidence`, `docker_runtime` |
| `target` | Path or object being audited/pruned |
| `ownership_class` | Whether the object is repo-exclusive, workspace state, or shared-related |
| `reclaim_class` | Whether the object is safe rebuildable, cautious evidence, protected, or shared-related |
| `dry_run` | Whether the command was audit-only |
| `size_before_kib` | Size before cleanup, in KiB |
| `size_after_kib` | Size after cleanup, in KiB |
| `reclaimed_kib` | Reclaimed amount, in KiB |

## 4. Exception Logging Rules

Exceptions must be logged as structured objects, not loose strings:

| Field | Meaning |
| --- | --- |
| `error.type` | Exception type |
| `error.code` | Error code, or `UNKNOWN` when missing |
| `error.message` | Error message without sensitive values |
| `error.stack` | Stack trace, truncation allowed |
| `error.retryable` | Whether retry is allowed |
| `error.cause` | Short causal chain summary |

Current implementation conventions:

- Python call sites pass `error_type/error_code/error_message/error_stack/error_retryable/error_cause`.
- JSON output normalizes them into `error.{type,code,message,stack,retryable,cause}`.

Every exception log must also include:

- A redacted summary of the current action and input
- The post-failure decision: retry, skip, abort, or rollback

## 5. Security And Redaction

- Never print `token`, `api key`, `password`, private keys, full credential URIs, or raw PII.
- Prefer relative or redacted paths so logs do not leak private local directories.
- Redaction must stay aligned with `tooling/gates/secret_scan.sh`.

## 6. Merge Gate (No Logs No Merge)

The merge must be blocked when any of the following is true:

- A critical-path logic change ships without new/updated structured logs.
- Logs are missing `trace_id` or structured exception fields.
- Exceptions are swallowed without an event record and context.
- Tests do not cover key log fields such as `event`, `status`, and `trace_id`.
- Low-quality log phrases such as `something went wrong` or `unknown error` appear without an explicit exemption marker.

Default enforcement gates:

- `bash tooling/gates/quality_gate.sh`
- `bash tooling/gates/pre_push_gate.sh`

## 7. Recommended Event Names

- `manifest.load.start` / `manifest.load.success` / `manifest.load.fail`
- `analyze.scan.start` / `analyze.scan.success` / `analyze.scan.fail`
- `apply.move.start` / `apply.move.success` / `apply.move.fail`
- `rollback.restore.start` / `rollback.restore.success` / `rollback.restore.fail`
- `report.generate.start` / `report.generate.success` / `report.generate.fail`
- `runtime.audit.start` / `runtime.audit.success` / `runtime.audit.fail`
- `cleanup.plan.start` / `cleanup.plan.success` / `cleanup.plan.fail`
- `cleanup.prune.start` / `cleanup.prune.success` / `cleanup.prune.fail`
- `docker.runtime.audit.start` / `docker.runtime.audit.success` / `docker.runtime.audit.fail`
- `docker.runtime.prune.start` / `docker.runtime.prune.success` / `docker.runtime.prune.fail`
- `receipt.retention.prune.start` / `receipt.retention.prune.success` / `receipt.retention.prune.fail`

Required cleanup/audit context fields:

| Field | Meaning |
| --- | --- |
| `bucket` | Governance rail such as `repo_local`, `machine_cache`, `workspace_evidence`, or `docker_runtime` |
| `target` | Named cleanup target or audit surface |
| `ownership_class` | Whether the surface is repo-exclusive, workspace-owned, fallback-host, or shared-related |
| `reclaim_class` | Cleanup safety class such as `safe_machine_cache` or `protected_canonical_image` |
| `dry_run` | Whether the command was audit-only |
| `size_before_kib` | Size before the action |
| `size_after_kib` | Size after the action |
| `reclaimed_kib` | Reclaimed size for terminal prune events |

## 8. SLI/SLO And Alerting Baseline

- SLI (must stay observable):
  - `cli.report.duration_ms`
  - `cli.rollback.dry_run.duration_ms`
  - `fileman.error_rate` aggregated by `event + status=fail`
- SLO (release baseline):
  - `cli.report.duration_ms <= 1500ms`
  - `cli.rollback.dry_run.duration_ms <= 3000ms`
  - `fileman.error_rate <= 1%` over a 7-day window
- Error budget:
  - 1% per rolling 7-day window; budget exhaustion triggers release downgrade (`AUDIT_ONLY`) or a hard stop
- Tracing:
  - Every critical-path log must carry `trace_id` for replay and correlation
- Alerting:
  - Trigger an alert when any SLO fails for two consecutive windows, or when a single `error.code` spikes abnormally
- Executable evidence commands:
  - `bash tooling/gates/check_observability_baseline.sh`
  - `bash tooling/gates/check_cli_perf_baseline.sh --budget-ms 1500`
  - `bash tooling/gates/check_rollback_rto.sh --budget-ms 3000`

## 9. Minimal Example (JSON)

```json
{
  "timestamp": "2026-02-25T15:40:00Z",
  "level": "ERROR",
  "event": "apply.move.fail",
  "trace_id": "trc_9f1b2c",
  "module": "packages.application.apply_command",
  "action": "move_file",
  "status": "fail",
  "duration_ms": 129,
  "user_id": "u_anon_001",
  "session_id": "sess_20260225_01",
  "request_id": "req_20260225_99",
  "manifest_id": "manifest_20260225.json",
  "target_path": "<workspace-root>/data/organized/video.mp4",
  "error": {
    "type": "PermissionError",
    "code": "FS_PERMISSION_DENIED",
  "message": "write denied for target path",
    "stack": "PermissionError: ...",
    "retryable": false,
    "cause": "insufficient filesystem permission"
  }
}
```
