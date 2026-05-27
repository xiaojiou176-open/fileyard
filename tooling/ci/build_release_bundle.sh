#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$ROOT")"
CONFIG_LIB="$ROOT/scripts/lib_config.sh"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"
VENV="$(governance_runtime_venv_path "$REPO_ROOT")"

VERSION_TAG="${1:-}"
OUTPUT_DIR="${2:-.runtime-cache/build/tooling/release-assets}"

if [ -z "$VERSION_TAG" ]; then
  echo "Usage: bash tooling/ci/build_release_bundle.sh <tag-or-version> [output-dir]" >&2
  exit 2
fi

bash "$ROOT/ci/validate_release_tag.sh" "$VERSION_TAG" bundle-only

if [ ! -x "$VENV/bin/python" ]; then
  bash "$ROOT/runtime/bootstrap_env.sh"
fi

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

notes_path="$OUTPUT_DIR/release-draft.md"
evidence_path="$OUTPUT_DIR/release-evidence.json"
manifest_path="$OUTPUT_DIR/release-manifest.json"
python_sbom_path="$OUTPUT_DIR/python-runtime-sbom.cdx.json"
node_sbom_path="$OUTPUT_DIR/webui-runtime-sbom.cdx.json"
source_archive_path="$OUTPUT_DIR/fileyard-${VERSION_TAG}.tar.gz"
checksums_path="$OUTPUT_DIR/SHA256SUMS.txt"

"$VENV/bin/python" "$ROOT/ci/prepare_release_draft.py" --root "$REPO_ROOT" --output "$notes_path"
"$VENV/bin/python" "$ROOT/scripts/generate_release_evidence_report.py" --root "$REPO_ROOT" --output "$evidence_path"

"$VENV/bin/python" -m pip_audit \
  --progress-spinner off \
  --disable-pip \
  --no-deps \
  -r "$REPO_ROOT/tooling/requirements.lock.txt" \
  -f cyclonedx-json \
  -o "$python_sbom_path"

npm --prefix "$REPO_ROOT/apps/webui" sbom \
  --package-lock-only \
  --sbom-format cyclonedx \
  --omit dev >"$node_sbom_path"

git -C "$REPO_ROOT" archive \
  --format=tar.gz \
  --prefix="fileyard-${VERSION_TAG}/" \
  -o "$source_archive_path" HEAD

python3 - <<'PY' "$manifest_path" "$VERSION_TAG" "$REPO_ROOT" "$notes_path" "$evidence_path" "$python_sbom_path" "$node_sbom_path" "$source_archive_path" "$checksums_path"
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
tag_name = sys.argv[2]
repo_root = Path(sys.argv[3])
notes_path = Path(sys.argv[4])
evidence_path = Path(sys.argv[5])
python_sbom_path = Path(sys.argv[6])
node_sbom_path = Path(sys.argv[7])
source_archive_path = Path(sys.argv[8])
checksums_path = Path(sys.argv[9])

source_commit = subprocess.run(
    ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
    text=True,
    capture_output=True,
    check=True,
).stdout.strip()

is_prerelease = "-" in tag_name
payload = {
    "schema_version": 1,
    "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    "tag_name": tag_name,
    "source_commit": source_commit,
    "is_prerelease": is_prerelease,
    "expected_assets": [
        notes_path.name,
        evidence_path.name,
        manifest_path.name,
        python_sbom_path.name,
        node_sbom_path.name,
        source_archive_path.name,
        checksums_path.name,
    ],
    "local_bundle_verification": {
        "checksums_file": checksums_path.name,
        "verify_entrypoint": f"bash tooling/ci/verify_release_publish.sh {tag_name} <draft|publish> {manifest_path.parent}",
    },
    "remote_release_boundary": {
        "bundle_only": "repo-side bundle proof only; no remote tag or GitHub Release is expected",
        "draft_or_publish": "requires remote tag materialization, GitHub Release asset upload, and post-publish verification",
    },
}
manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

python3 - <<'PY' "$checksums_path" "$notes_path" "$evidence_path" "$manifest_path" "$python_sbom_path" "$node_sbom_path" "$source_archive_path"
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

out = Path(sys.argv[1])
items = [Path(p) for p in sys.argv[2:]]
lines = []
for item in items:
    digest = hashlib.sha256(item.read_bytes()).hexdigest()
    lines.append(f"{digest}  {item.name}")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

printf '%s\n' "release bundle built: $OUTPUT_DIR"
