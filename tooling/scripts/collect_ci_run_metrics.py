#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
TRACKED_SNIPPETS = (
    "quality_gate.sh",
    "functional_gate.sh",
    "docs_smoke.sh --install-smoke",
    "secret_scan.sh",
    "check_required_checks_matrix.py",
    "check_env_contract.py",
    "check_runner_capabilities.sh",
    "check_runner_inventory.py",
    "npm --prefix apps/webui run test",
    "npm --prefix apps/webui run build",
    "pip-audit",
    "pytest",
)
LOCAL_GATE_LOGS: tuple[tuple[str, str], ...] = (
    ("quality-gate", ".runtime-cache/logs/quality-gate"),
    ("functional-gate", ".runtime-cache/logs/functional-gate"),
    ("local-ci-matrix", ".runtime-cache/logs/local-ci-matrix"),
    ("docs-smoke", ".runtime-cache/logs/quality-gate/docs-smoke.log"),
    ("ci-hardening", ".runtime-cache/logs/ci-hardening.local.log"),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect CI job timing and failure-rate metrics.")
    parser.add_argument("--output", default=".runtime-cache/logs/ci-run-metrics.json")
    parser.add_argument("--recent-runs", type=int, default=5)
    return parser.parse_args()


def _github_get(path: str, token: str) -> dict[str, Any]:
    req = Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "fileman-ci-run-metrics",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(req, timeout=30) as resp:  # nosec B310
        return json.loads(resp.read().decode("utf-8"))


def _duration_seconds(started_at: str | None, completed_at: str | None) -> float | None:
    if not started_at or not completed_at:
        return None
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    return round((end - start).total_seconds(), 3)


def _load_duplication_hints() -> dict[str, list[str]]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs", {}) if isinstance(workflow, dict) else {}
    job_tokens: dict[str, list[str]] = {}
    counter: Counter[str] = Counter()
    for job_id, raw_job in jobs.items():
        if not isinstance(raw_job, dict):
            continue
        tokens: list[str] = []
        for step in raw_job.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            run_text = str(step.get("run", ""))
            for snippet in TRACKED_SNIPPETS:
                if snippet in run_text:
                    tokens.append(snippet)
        deduped = sorted(set(tokens))
        job_tokens[job_id] = deduped
        counter.update(deduped)
    duplicates: dict[str, list[str]] = {}
    for job_id, tokens in job_tokens.items():
        duplicates[job_id] = [token for token in tokens if counter[token] > 1]
    return duplicates


def _scan_log_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return ""


def _summarize_local_gate(name: str, path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    logs: list[Path]
    if path.is_dir():
        logs = sorted(item for item in path.rglob("*.log") if item.is_file())
        if not logs:
            return None
    else:
        logs = [path]

    combined = "\n".join(_scan_log_text(item) for item in logs)
    status = "unknown"
    if any(token in combined for token in (" failed", "❌", "error:", "traceback")):
        status = "failed"
    if any(token in combined for token in (" passed", "✅", "all checks passed", "version-parity unit suite passed")):
        status = "passed" if status != "failed" else "failed"

    return {
        "name": name,
        "status": status,
        "conclusion": "success" if status == "passed" else ("failure" if status == "failed" else "unknown"),
        "duration_seconds": None,
        "html_url": None,
        "duplication_tokens": _load_duplication_hints().get(name, []),
    }


def main() -> int:
    args = _parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    token = os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GH_TOKEN", "").strip()
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()

    duplication_hints = _load_duplication_hints()
    payload: dict[str, Any] = {
        "status": "skipped",
        "reason": None,
        "current_run": [],
        "recent_failure_rates": {},
        "duplication_hints": duplication_hints,
    }

    if not token or not repository or not run_id:
        local_jobs = [
            item for item in (_summarize_local_gate(name, REPO_ROOT / rel_path) for name, rel_path in LOCAL_GATE_LOGS) if item is not None
        ]
        payload["status"] = "local"
        payload["reason"] = "local-artifact-derived"
        payload["current_run"] = local_jobs
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"✅ ci_run_metrics: wrote {output} (local)")
        return 0

    try:
        run_data = _github_get(f"/repos/{repository}/actions/runs/{run_id}", token)
        jobs_data = _github_get(f"/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100", token)
        workflow_id = run_data.get("workflow_id")
        recent_runs = _github_get(
            f"/repos/{repository}/actions/workflows/{workflow_id}/runs?per_page={args.recent_runs}",
            token,
        )
    except HTTPError as exc:
        payload["reason"] = f"github_api_http_{exc.code}"
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"✅ ci_run_metrics: wrote {output} (skipped: {payload['reason']})")
        return 0

    current_jobs = []
    jobs = jobs_data.get("jobs", []) if isinstance(jobs_data, dict) else []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        current_jobs.append(
            {
                "name": job.get("name"),
                "status": job.get("status"),
                "conclusion": job.get("conclusion"),
                "duration_seconds": _duration_seconds(job.get("started_at"), job.get("completed_at")),
                "html_url": job.get("html_url"),
                "duplication_tokens": duplication_hints.get(str(job.get("name", "")), []),
            }
        )

    recent_failure_counts: dict[str, list[bool]] = defaultdict(list)
    recent_runs_list = recent_runs.get("workflow_runs", []) if isinstance(recent_runs, dict) else []
    for run in recent_runs_list:
        if not isinstance(run, dict):
            continue
        run_jobs_data = _github_get(f"/repos/{repository}/actions/runs/{run['id']}/jobs?per_page=100", token)
        for job in run_jobs_data.get("jobs", []) if isinstance(run_jobs_data, dict) else []:
            if not isinstance(job, dict):
                continue
            name = str(job.get("name", ""))
            recent_failure_counts[name].append(job.get("conclusion") != "success")

    failure_rates = {
        name: {
            "recent_runs": len(values),
            "failed_runs": sum(1 for value in values if value),
            "failure_rate": round(sum(1 for value in values if value) / len(values), 3) if values else 0.0,
        }
        for name, values in sorted(recent_failure_counts.items())
    }

    payload.update(
        {
            "status": "ok",
            "reason": None,
            "current_run": current_jobs,
            "recent_failure_rates": failure_rates,
        }
    )
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ ci_run_metrics: wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
