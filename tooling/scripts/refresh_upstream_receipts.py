#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_bundle(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid bundle json: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid bundle payload type: {path}")
    return payload


def _ensure_bundle_is_green(bundle: dict[str, Any], bundle_path: Path) -> None:
    summary = bundle.get("summary")
    if not isinstance(summary, dict):
        raise SystemExit(f"bundle summary missing: {bundle_path}")
    overall = str(summary.get("overall_status", "")).strip()
    if overall != "passed":
        raise SystemExit(f"bundle summary is not green: {bundle_path} overall_status={overall or 'missing'}")

    upstream_summary = bundle.get("upstream_summary")
    if not isinstance(upstream_summary, dict):
        raise SystemExit(f"bundle upstream_summary missing: {bundle_path}")
    if str(upstream_summary.get("status", "")).strip() != "ok":
        raise SystemExit(f"bundle upstream_summary is not ok: {bundle_path}")


def _resolve_bundle_path(repo_root: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else repo_root / path


def _default_bundle_candidates(repo_root: Path) -> list[Path]:
    return [
        repo_root / ".runtime-cache" / "ci" / "evidence-bundle.json",
        repo_root / ".runtime-cache" / "logs" / "evidence-bundle.local.json",
    ]


def _apply_runtime_hygiene() -> None:
    pycache_prefix = str(Path(os.environ.get("PYTHONPYCACHEPREFIX", "~/.cache/fileman/pycache")).expanduser())
    Path(pycache_prefix).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    os.environ.setdefault("PYTHONPYCACHEPREFIX", pycache_prefix)
    sys.dont_write_bytecode = True
    sys.pycache_prefix = pycache_prefix


def main() -> int:
    _apply_runtime_hygiene()
    from tooling.scripts.generate_ci_evidence_bundle import (
        _redact_sensitive_payload,
        _safe_bundle_projection,
        _write_upstream_receipts,
        build_bundle,
    )

    parser = argparse.ArgumentParser(description="Refresh or import governed upstream receipt artifacts from an evidence bundle")
    parser.add_argument("--root", default=".")
    parser.add_argument("--bundle", help="Existing evidence bundle to import receipts from")
    parser.add_argument("--artifacts-root", help="Artifacts root used to build a fresh evidence bundle before writing receipts")
    parser.add_argument(
        "--output-bundle",
        default=".runtime-cache/ci/evidence-bundle.json",
        help="Bundle output path when building from artifacts-root",
    )
    parser.add_argument(
        "--summary-output",
        default=".runtime-cache/ci/upstream-receipts/summary.json",
        help="Receipt summary output path",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()

    if args.bundle and args.artifacts_root:
        raise SystemExit("choose either --bundle or --artifacts-root, not both")

    source_mode = "import"
    if args.artifacts_root:
        artifacts_root = _resolve_bundle_path(repo_root, args.artifacts_root)
        bundle_path = _resolve_bundle_path(repo_root, args.output_bundle)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle = build_bundle(artifacts_root)
        bundle_path.write_text(json.dumps(_safe_bundle_projection(bundle), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        source_mode = "build"
    elif args.bundle:
        bundle_path = _resolve_bundle_path(repo_root, args.bundle)
        if not bundle_path.exists():
            raise SystemExit(f"bundle not found: {bundle_path}")
        bundle = _load_bundle(bundle_path)
    else:
        bundle_candidate = next((path for path in _default_bundle_candidates(repo_root) if path.exists()), None)
        if bundle_candidate is None:
            raise SystemExit("no evidence bundle available; pass --bundle or --artifacts-root")
        bundle_path = bundle_candidate
        bundle = _load_bundle(bundle_path)

    _ensure_bundle_is_green(bundle, bundle_path)
    written = _write_upstream_receipts(repo_root, bundle, bundle_path)

    summary_path = _resolve_bundle_path(repo_root, args.summary_output)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "status": "ok",
        "source_mode": source_mode,
        "bundle_path": str(bundle_path),
        "bundle_summary": bundle.get("summary", {}),
        "receipt_count": len(written),
        "receipts": written,
    }
    summary_path.write_text(json.dumps(_redact_sensitive_payload(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"upstream receipts refreshed: {len(written)}")
    print(f"source_mode={source_mode}")
    print(f"bundle_path={bundle_path}")
    print(f"summary_path={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
