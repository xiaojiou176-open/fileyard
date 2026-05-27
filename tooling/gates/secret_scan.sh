#!/usr/bin/env bash
set -euo pipefail
# Secret scanning with incremental support.
# CI quality_gate compatibility: allow grep fallback when ripgrep is unavailable.
#
# Modes:
#   (default): scan entire repository
#   --staged-only: scan only staged files (for pre-commit)
#   --changed-only: scan only changed files since merge-base (for pre-push)

ROOT_DIR=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
CONFIG_LIB="$REPO_ROOT/tooling/scripts/lib_config.sh"
SCAN_MODE="full"

if [ ! -f "$CONFIG_LIB" ]; then
  echo "❌ secret_scan: missing config helper: $CONFIG_LIB" >&2
  exit 2
fi
source "$CONFIG_LIB"
IFS='|' read -r ALLOW_EXTERNAL ALLOW_EXTERNAL_SOURCE \
  <<< "$(resolve_allow_external_with_source "0")"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --root)
      ROOT_DIR="$2"
      shift 2
      ;;
    --staged-only)
      SCAN_MODE="staged"
      shift
      ;;
    --changed-only)
      SCAN_MODE="changed"
      shift
      ;;
    *)
      if [ -z "$ROOT_DIR" ]; then
        ROOT_DIR="$1"
      fi
      shift
      ;;
  esac
done

if [ -z "$ROOT_DIR" ]; then
  ROOT_DIR="."
fi

HAS_RG=0
if command -v rg >/dev/null 2>&1; then
  HAS_RG=1
fi

ROOT_DIR="$(cd "$ROOT_DIR" && pwd -P)"

if [ ! -d "$ROOT_DIR" ]; then
  echo "❌ secret_scan: root dir not found: $ROOT_DIR" >&2
  exit 2
fi
if [ "$ROOT_DIR" = "/" ]; then
  echo "❌ secret_scan: refusing to scan filesystem root" >&2
  exit 2
fi
if [[ "$ALLOW_EXTERNAL" != "1" && "$ROOT_DIR" != "$REPO_ROOT" && "$ROOT_DIR" != "$REPO_ROOT"/* ]]; then
  echo "❌ secret_scan: refusing to scan outside repository: $ROOT_DIR" >&2
  exit 2
fi

echo "==> secret_scan mode=${SCAN_MODE} allow-external=${ALLOW_EXTERNAL} source=${ALLOW_EXTERNAL_SOURCE}"

# Build file list based on scan mode
build_file_list() {
  local file_list="$1"
  : > "$file_list"

  case "$SCAN_MODE" in
    staged)
      if command -v git >/dev/null 2>&1; then
        git -C "$REPO_ROOT" diff --cached --name-only --diff-filter=ACMRT 2>/dev/null \
          | while IFS= read -r f; do
              if [ -f "$REPO_ROOT/$f" ]; then
                echo "$REPO_ROOT/$f"
              fi
            done > "$file_list"
      fi
      ;;
    changed)
      if command -v git >/dev/null 2>&1; then
        local base_ref=""
        if git -C "$REPO_ROOT" rev-parse --verify origin/main >/dev/null 2>&1; then
          base_ref="$(git -C "$REPO_ROOT" merge-base HEAD origin/main 2>/dev/null || true)"
        elif git -C "$REPO_ROOT" rev-parse --verify origin/master >/dev/null 2>&1; then
          base_ref="$(git -C "$REPO_ROOT" merge-base HEAD origin/master 2>/dev/null || true)"
        fi
          if [ -z "$base_ref" ]; then
            local roots=""
            base_ref="$(git -C "$REPO_ROOT" rev-parse HEAD~10 2>/dev/null || true)"
            if [ -z "$base_ref" ]; then
              roots="$(git -C "$REPO_ROOT" rev-list --max-parents=0 HEAD 2>/dev/null || true)"
            base_ref="${roots%%$'\n'*}"
          fi
        fi
        git -C "$REPO_ROOT" diff --name-only --diff-filter=ACMRT "$base_ref" HEAD 2>/dev/null \
          | while IFS= read -r f; do
              if [ -f "$REPO_ROOT/$f" ]; then
                echo "$REPO_ROOT/$f"
              fi
            done > "$file_list"
      fi
      ;;
    full)
      # Return empty to signal full scan
      ;;
  esac
}

# Check for tracked .env files (always run)
if command -v git >/dev/null 2>&1; then
  if [ "$HAS_RG" -eq 1 ]; then
    TRACKED_ENV_FILES="$(
      git -C "$REPO_ROOT" ls-files \
        | rg '(^|/)\.env(\.[^/]+)?$' \
        | rg -v '(^|/)\.env\.example$' || true
    )"
  else
    TRACKED_ENV_FILES="$(
      git -C "$REPO_ROOT" ls-files \
        | grep -E '(^|/)\.env(\.[^/]+)?$' \
        | grep -Ev '(^|/)\.env\.example$' || true
    )"
  fi
  if [ -n "$TRACKED_ENV_FILES" ]; then
    echo "❌ secret_scan: tracked .env files detected (only .env.example is allowed):" >&2
    echo "$TRACKED_ENV_FILES" >&2
    exit 1
  fi
fi

# Policy check for sensitive keys (always run on policy files)
if command -v python3 >/dev/null 2>&1; then
  set +e
  python3 - "$REPO_ROOT" <<'PY'
import re
import sys
from pathlib import Path

repo = Path(sys.argv[1])
sensitive_keys = {
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "FILEORGANIZE_ROLLBACK_HMAC_KEY",
}
placeholder_tokens = {
    "",
    "changeme",
    "your_api_key",
    "<your_api_key>",
    "placeholder",
    "dummy",
    "test",
}

def normalize_value(raw: str) -> str:
    value = raw.split("#", 1)[0].strip().rstrip(",")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value.strip()

def is_allowed_value(value: str) -> bool:
    if value == "":
        return True
    lowered = value.lower()
    if lowered in placeholder_tokens:
        return True
    if value.startswith("${") or value.startswith("$"):
        return True
    return False

violations: list[str] = []

env_example = repo / ".env.example"
if env_example.exists():
    for lineno, raw in enumerate(env_example.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in sensitive_keys:
            continue
        parsed = normalize_value(value)
        if not is_allowed_value(parsed):
            violations.append(
                f"{env_example}:{lineno}: sensitive key template must be empty/placeholder/env-ref, got literal value"
            )

policy_files: list[Path] = []
compose_file = repo / "ops" / "compose" / "docker-compose.yml"
if compose_file.exists():
    policy_files.append(compose_file)

devcontainer_dir = repo / ".devcontainer"
if devcontainer_dir.exists():
    for candidate in sorted(devcontainer_dir.rglob("*")):
        if not candidate.is_file():
            continue
        if candidate.name == "Dockerfile" or candidate.suffix.lower() in {".json", ".yml", ".yaml", ".env"}:
            policy_files.append(candidate)

for path in policy_files:
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        matched = None
        for key in sensitive_keys:
            if re.search(rf"\b{re.escape(key)}\b", line):
                matched = key
                break
        if not matched:
            continue
        # allow key declaration with empty value in JSON/YAML
        if re.fullmatch(rf'.*{re.escape(matched)}\s*[:=]\s*["\']?\s*["\']?\s*,?\s*', line):
            continue
        value_part = re.split(rf"{re.escape(matched)}\s*[:=]", line, maxsplit=1)[-1]
        parsed = normalize_value(value_part)
        if not is_allowed_value(parsed):
            violations.append(
                f"{path}:{lineno}: sensitive key must come from .env/env var reference, got literal value"
            )

if violations:
    print("\n".join(violations))
    raise SystemExit(1)
PY
  POLICY_STATUS=$?
  set -e
  if [ "$POLICY_STATUS" -ne 0 ]; then
    echo "❌ secret_scan: key source policy violations detected:"
    exit 1
  fi
fi

PATTERN='(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)'

# Build file list for incremental modes
FILE_LIST_TMP=""
if [ "$SCAN_MODE" != "full" ]; then
  FILE_LIST_TMP="$(mktemp)"
  build_file_list "$FILE_LIST_TMP"

  if [ ! -s "$FILE_LIST_TMP" ]; then
    echo "✅ secret_scan: no files to scan in ${SCAN_MODE} mode"
    rm -f "$FILE_LIST_TMP"
    exit 0
  fi

  echo "==> secret_scan: scanning $(wc -l < "$FILE_LIST_TMP" | tr -d ' ') files"
fi

run_scan() {
  if [ "$SCAN_MODE" = "full" ]; then
    # Full repository scan
    if [ "$HAS_RG" -eq 1 ]; then
      rg \
        --hidden \
        --no-ignore \
        --line-number \
        --with-filename \
        --color never \
        --glob '!.env' \
        --glob '!.env.*' \
        --glob '!**/.env' \
        --glob '!**/.env.*' \
        --glob '!**/.venv/**' \
        --glob '!**/.venv-matrix/**' \
        --glob '!**/.venv-matrix-*/**' \
        --glob '!**/.git/**' \
        --glob '!**/.runtime-cache/**' \
        --glob '!**/data/**' \
        --glob '!**/artifacts/**' \
        --glob '!**/tooling/gates/secret_scan.sh' \
        -e "${PATTERN}" \
        "$ROOT_DIR"
    else
      grep -RInE \
        --binary-files=without-match \
        --exclude-dir=.git \
        --exclude-dir=.venv \
        --exclude-dir=.venv-matrix \
        --exclude-dir=.venv-matrix-* \
        --exclude-dir=.runtime-cache \
        --exclude-dir=artifacts \
        --exclude-dir=data \
        --exclude=.env \
        --exclude=.env.* \
        --exclude=secret_scan.sh \
        "${PATTERN}" \
        "$ROOT_DIR"
    fi
  else
    # Incremental scan - only specified files
    local files_to_scan=()
    while IFS= read -r f; do
      # Skip excluded files
      case "$f" in
        */.env|*/.env.*|*/.git/*|*/.venv/*|*/.venv-matrix/*|*/artifacts/*|*/data/*|*/.runtime-cache/*|*/secret_scan.sh)
          continue
          ;;
      esac
      if [ -f "$f" ]; then
        files_to_scan+=("$f")
      fi
    done < "$FILE_LIST_TMP"

    if [ "${#files_to_scan[@]}" -eq 0 ]; then
      return 1  # No matches (success)
    fi

    if [ "$HAS_RG" -eq 1 ]; then
      rg \
        --line-number \
        --with-filename \
        --color never \
        -e "${PATTERN}" \
        "${files_to_scan[@]}"
    else
      grep -HnE "${PATTERN}" "${files_to_scan[@]}"
    fi
  fi
}

run_scan_from_git_index() {
  if ! command -v git >/dev/null 2>&1; then
    return 2
  fi
  local files_to_scan=()
  while IFS= read -r f; do
    case "$f" in
      .env|.env.*|*/.env|*/.env.*|*/.git/*|*/.venv/*|*/.venv-matrix/*|*/artifacts/*|*/data/*|*/.runtime-cache/*|*/secret_scan.sh)
        continue
        ;;
    esac
    if [ -f "$REPO_ROOT/$f" ]; then
      files_to_scan+=("$REPO_ROOT/$f")
    fi
  done < <(git -C "$REPO_ROOT" ls-files)

  if [ "${#files_to_scan[@]}" -eq 0 ]; then
    return 1
  fi

  if [ "$HAS_RG" -eq 1 ]; then
    rg \
      --line-number \
      --with-filename \
      --color never \
      -e "${PATTERN}" \
      "${files_to_scan[@]}"
  else
    grep -HnE "${PATTERN}" "${files_to_scan[@]}"
  fi
}

set +e
SCAN_OUTPUT="$(run_scan 2>&1)"
SCAN_STATUS=$?
set -e

if [ "${SCAN_STATUS}" -gt 1 ] && [ "$SCAN_MODE" = "full" ]; then
  echo "⚠️ secret_scan: full-tree scan returned ${SCAN_STATUS}; retry with git-indexed file set" >&2
  set +e
  SCAN_OUTPUT="$(run_scan_from_git_index 2>&1)"
  SCAN_STATUS=$?
  set -e
fi

# Cleanup temp file
if [ -n "$FILE_LIST_TMP" ] && [ -f "$FILE_LIST_TMP" ]; then
  rm -f "$FILE_LIST_TMP"
fi

if [ "${SCAN_STATUS}" -eq 0 ]; then
  echo "❌ secret_scan: potential secrets found:"
  echo "${SCAN_OUTPUT}"
  exit 1
fi

if [ "${SCAN_STATUS}" -eq 1 ]; then
  echo "✅ secret_scan: no secrets detected"
  exit 0
fi

echo "❌ secret_scan: scan failed (exit code ${SCAN_STATUS})" >&2
exit "${SCAN_STATUS}"
