#!/usr/bin/env bash
set -euo pipefail

# Post-publish gate: verify the remote GitHub Release still matches the
# locally built bundle after the release workflow / quality_gate path lands.

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "Usage: bash tooling/ci/verify_release_publish.sh <tag-name> <publish-mode> [local-bundle-dir]" >&2
  exit 2
fi

tag_name="$1"
publish_mode="$2"
local_bundle_dir="${3:-}"
summary_path="${RELEASE_VERIFY_SUMMARY_OUT:-.runtime-cache/logs/release-publish/summary.json}"

mkdir -p "$(dirname "$summary_path")"

write_shell_summary() {
  local status="$1"
  local reason="$2"
  python3 - "$summary_path" "$tag_name" "$publish_mode" "$status" "$reason" <<'PY'
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
payload = {
    "schema_version": 1,
    "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    "tag_name": sys.argv[2],
    "publish_mode": sys.argv[3],
    "status": sys.argv[4],
    "reason": sys.argv[5],
}
summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

case "$publish_mode" in
  bundle-only)
    echo "bundle-only mode: remote release verification skipped"
    write_shell_summary "skipped" "bundle-only mode intentionally stops before remote GitHub Release creation"
    exit 0
    ;;
  draft|publish) ;;
  *)
    echo "Unsupported publish mode: $publish_mode" >&2
    exit 2
    ;;
esac

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required for release verification" >&2
  write_shell_summary "fail" "gh CLI is required for release verification"
  exit 1
fi

if ! payload="$(gh release view "$tag_name" --json tagName,isDraft,isPrerelease,assets,url,targetCommitish 2>&1)"; then
  echo "$payload" >&2
  write_shell_summary "fail" "$payload"
  exit 1
fi

payload_file="$(mktemp)"
trap 'rm -f "$payload_file"' EXIT
printf '%s' "$payload" >"$payload_file"

python3 - "$tag_name" "$publish_mode" "$local_bundle_dir" "$summary_path" "$payload_file" <<'PY'
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

tag_name = sys.argv[1]
publish_mode = sys.argv[2]
bundle_dir_raw = sys.argv[3]
summary_path = Path(sys.argv[4])
payload_path = Path(sys.argv[5])
payload = json.loads(payload_path.read_text(encoding="utf-8"))

summary: dict[str, object] = {
    "schema_version": 1,
    "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    "tag_name": tag_name,
    "publish_mode": publish_mode,
    "status": "fail",
    "release_url": payload.get("url"),
    "release_target_commitish": payload.get("targetCommitish"),
    "is_draft": bool(payload.get("isDraft")),
    "is_prerelease": bool(payload.get("isPrerelease")),
    "remote_asset_names": sorted(asset.get("name", "") for asset in payload.get("assets", []) if isinstance(asset, dict)),
    "local_bundle_dir": bundle_dir_raw or None,
}

bundle_dir = Path(bundle_dir_raw).resolve() if bundle_dir_raw else None
manifest = None
expected_assets = {
    f"fileman-{tag_name}.tar.gz",
    "release-draft.md",
    "release-evidence.json",
    "python-runtime-sbom.cdx.json",
    "webui-runtime-sbom.cdx.json",
    "SHA256SUMS.txt",
}
local_checksums_path = None

if bundle_dir is not None:
    manifest_path = bundle_dir / "release-manifest.json"
    if not manifest_path.exists():
        summary["reason"] = f"local bundle manifest missing: {manifest_path}"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(summary["reason"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_assets = set(manifest.get("expected_assets", []))
    local_checksums_path = bundle_dir / "SHA256SUMS.txt"
    if not local_checksums_path.exists():
        summary["reason"] = f"local bundle checksums missing: {local_checksums_path}"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(summary["reason"])
    if str(manifest.get("tag_name", "")).strip() != tag_name:
        summary["reason"] = "local bundle manifest tag does not match verification tag"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(summary["reason"])
    expected_commit = str(manifest.get("source_commit", "")).strip()
    if expected_commit and str(payload.get("targetCommitish", "")).strip() != expected_commit:
        summary["reason"] = (
            f"release target commit mismatch: remote={payload.get('targetCommitish')} expected={expected_commit}"
        )
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(summary["reason"])
    expected_prerelease = bool(manifest.get("is_prerelease"))
    if bool(payload.get("isPrerelease")) != expected_prerelease:
        summary["reason"] = (
            f"release prerelease mismatch: remote={bool(payload.get('isPrerelease'))} expected={expected_prerelease}"
        )
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(summary["reason"])

asset_names = set(summary["remote_asset_names"])
missing = sorted(expected_assets - asset_names)
if missing:
    summary["reason"] = "missing release assets: " + ", ".join(missing)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(summary["reason"])

is_draft = bool(payload.get("isDraft"))
if publish_mode == "draft" and not is_draft:
    summary["reason"] = "expected draft release after draft stage"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(summary["reason"])
if publish_mode == "publish" and is_draft:
    summary["reason"] = "expected published release after publish stage"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(summary["reason"])


def parse_checksums(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        mapping[name] = digest
    return mapping


tmpdir = Path(tempfile.mkdtemp(prefix="release-verify-"))
try:
    for asset_name in sorted(expected_assets):
        proc = subprocess.run(
            ["gh", "release", "download", tag_name, "--dir", str(tmpdir), "--clobber", "--pattern", asset_name],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            summary["reason"] = f"failed to download release asset {asset_name}: {proc.stderr.strip() or proc.stdout.strip()}"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(summary["reason"])

    remote_checksums_path = tmpdir / "SHA256SUMS.txt"
    if not remote_checksums_path.exists():
        summary["reason"] = "downloaded release assets missing SHA256SUMS.txt"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(summary["reason"])
    remote_checksums = parse_checksums(remote_checksums_path)
    if bundle_dir is not None and local_checksums_path is not None:
        local_checksums_text = local_checksums_path.read_text(encoding="utf-8")
        remote_checksums_text = remote_checksums_path.read_text(encoding="utf-8")
        if local_checksums_text != remote_checksums_text:
            summary["reason"] = "remote SHA256SUMS.txt does not match local bundle"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(summary["reason"])
    for asset_name in sorted(expected_assets):
        if asset_name == "SHA256SUMS.txt":
            continue
        asset_path = tmpdir / asset_name
        if not asset_path.exists():
            summary["reason"] = f"downloaded asset missing after verification: {asset_name}"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(summary["reason"])
        digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        if remote_checksums.get(asset_name) != digest:
            summary["reason"] = f"checksum mismatch for remote asset: {asset_name}"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(summary["reason"])
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

summary["status"] = "pass"
summary["reason"] = "remote release assets, tag target, prerelease state, and checksums verified"
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"release verification ok: {payload['tagName']} -> {payload['url']}")
PY
