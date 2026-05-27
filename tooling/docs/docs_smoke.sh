#!/usr/bin/env bash
set -euo pipefail
# This gate only smoke-checks command/install documentation surfaces.
# It does not prove full docs governance or full docs truth alignment by itself.
# CI quality_gate compatibility: allow grep fallback when ripgrep is unavailable.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOC_ROOT="$(dirname "$DIR")"
REPO_ROOT="$(dirname "$DOC_ROOT")"
CONFIG_LIB="$DOC_ROOT/scripts/lib_config.sh"
INSTALL_SMOKE=0
DOCS_NAV_REGISTRY="$REPO_ROOT/contracts/docs/docs_nav_registry.yaml"
DOCS_SMOKE_ENTRYPOINT_TIMEOUT_SECONDS="${DOCS_SMOKE_ENTRYPOINT_TIMEOUT_SECONDS:-5}"

# shellcheck source=tooling/scripts/lib_config.sh
. "$CONFIG_LIB"
load_governance_defaults "$REPO_ROOT"
apply_runtime_env_defaults "$REPO_ROOT"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --install-smoke)
      INSTALL_SMOKE=1
      shift
      ;;
    *)
      echo "Usage: $0 [--install-smoke]" >&2
      exit 2
      ;;
  esac
done

CONFIG_PATH="$REPO_ROOT/contracts/runtime/config.example.toml"

fail_count=0
HAS_RG=0
if command -v rg >/dev/null 2>&1; then
  HAS_RG=1
fi

resolve_python_bin() {
  local runtime_venv
  runtime_venv="$(governance_runtime_venv_path "$REPO_ROOT")"
  if [ -x "$runtime_venv/bin/python" ]; then
    printf '%s\n' "$runtime_venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  echo "❌ docs_smoke (command/install docs only): python3 not found" >&2
  exit 1
}

DOCS_PYTHON="$(resolve_python_bin)"

list_command_smoke_docs() {
  "$DOCS_PYTHON" - "$REPO_ROOT" <<'PY'
from pathlib import Path
import sys
import yaml

repo_root = Path(sys.argv[1])
registry = yaml.safe_load((repo_root / "contracts" / "docs" / "docs_nav_registry.yaml").read_text(encoding="utf-8"))
for item in registry.get("docs", []):
    if item.get("command_smoke"):
        print(str(repo_root / str(item["path"])))
PY
}

require_config_example_docs() {
  "$DOCS_PYTHON" - "$REPO_ROOT" <<'PY'
from pathlib import Path
import sys
import yaml

repo_root = Path(sys.argv[1])
registry = yaml.safe_load((repo_root / "contracts" / "docs" / "docs_nav_registry.yaml").read_text(encoding="utf-8"))
for item in registry.get("docs", []):
    if item.get("requires_config_example"):
        print(str(repo_root / str(item["path"])))
PY
}

fail() {
  echo "❌ docs_smoke (command/install docs only): $*" >&2
  fail_count=$((fail_count + 1))
}

print_log_tail() {
  local log_file="$1"
  local label="$2"
  if [ -f "$log_file" ]; then
    echo "---- $label (tail -n 40) ----" >&2
    tail -n 40 "$log_file" >&2
    echo "--------------------------------" >&2
  fi
}

check_runtime_dependencies() {
  local python_bin="$1"
  "$python_bin" - <<'PY'
import sys

import fastapi  # noqa: F401
import google.genai  # noqa: F401
import multipart  # noqa: F401
import PIL  # noqa: F401
import uvicorn  # noqa: F401
import yaml  # noqa: F401

if sys.version_info < (3, 11):
    import tomli  # noqa: F401
PY
}

package_smoke_required_entrypoints() {
  local python_bin="$1"
  "$python_bin" - "$REPO_ROOT/pyproject.toml" <<'PY'
from pathlib import Path
import sys

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

path = Path(sys.argv[1])
data = tomllib.loads(path.read_text(encoding="utf-8"))
tool = data.get("tool", {})
fileorganize = tool.get("fileorganize", {}) if isinstance(tool, dict) else {}
package_smoke = fileorganize.get("package_smoke", {}) if isinstance(fileorganize, dict) else {}
entrypoints = package_smoke.get("required_entrypoints", []) if isinstance(package_smoke, dict) else []
for name in entrypoints:
    print(str(name))
PY
}

run_install_smoke_with_existing_venv() {
  local venv_path="$1"
  local log_file="$2"
  local build_dir="$3"
  local source_copy_dir="$4"
  local temp_root="$5"
  {
    echo "[docs_smoke] command/install smoke using existing venv: $venv_path"
    (
      cd "$source_copy_dir"
      TMPDIR="$temp_root" TMP="$temp_root" TEMP="$temp_root" \
        "$venv_path/bin/python" -m build --sdist --wheel --outdir "$build_dir"
    )
    wheel_path="$(find "$build_dir" -maxdepth 1 -name '*.whl' | head -n1)"
    if [ -z "${wheel_path:-}" ]; then
      echo "❌ docs_smoke (command/install docs only): packaging smoke failed to produce wheel artifact" >&2
      exit 1
    fi
    TMPDIR="$temp_root" TMP="$temp_root" TEMP="$temp_root" \
      "$venv_path/bin/python" -m pip install --disable-pip-version-check --no-build-isolation --no-deps --force-reinstall "$wheel_path"
    while IFS= read -r entrypoint; do
      [ -z "$entrypoint" ] && continue
      run_entrypoint_help_smoke "$venv_path/bin/python" "$venv_path/bin/${entrypoint}" "$entrypoint"
    done < <(package_smoke_required_entrypoints "$venv_path/bin/python")
    check_runtime_dependencies "$venv_path/bin/python"
  } >"$log_file" 2>&1
}

prepare_install_smoke_source() {
  local source_dir="$1"
  mkdir -p "$source_dir"
  "$DOCS_PYTHON" - "$REPO_ROOT" "$source_dir" <<'PY'
from __future__ import annotations

import shutil
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2]).resolve()
ignore_roots = {".git", ".runtime-cache", "node_modules", "build", "dist", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}

for child in source.iterdir():
    if child.name in ignore_roots:
        continue
    destination = target / child.name
    if child.is_dir():
        shutil.copytree(
            child,
            destination,
            ignore=shutil.ignore_patterns("__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules", "build", "dist"),
            dirs_exist_ok=True,
        )
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, destination)
PY
}

run_entrypoint_help_smoke() {
  local python_bin="$1"
  local entrypoint_path="$2"
  local entrypoint_name="$3"
  "$python_bin" "$DOC_ROOT/scripts/docs_smoke_entrypoint_check.py" \
    --entrypoint-path "$entrypoint_path" \
    --entrypoint-name "$entrypoint_name" \
    --timeout-seconds "$DOCS_SMOKE_ENTRYPOINT_TIMEOUT_SECONDS"
}

assert_file_exists() {
  local path="$1"
  local label="$2"
  if [ ! -f "$path" ]; then
    fail "$label not found: $path"
  fi
}

assert_file_exists "$DOCS_NAV_REGISTRY" "docs_nav_registry"
assert_file_exists "$CONFIG_PATH" "config example"

if ! "$DOCS_PYTHON" "$DOC_ROOT/scripts/check_docs_scope.py" --root "$REPO_ROOT" >/dev/null; then
  fail "docs scope validation failed (fix docs_nav_registry / archive / generated boundaries first)"
fi

while IFS= read -r required_doc; do
  [ -z "$required_doc" ] && continue
  assert_file_exists "$required_doc" "command-smoke document"
done < <(list_command_smoke_docs)

while IFS= read -r config_doc; do
  [ -z "$config_doc" ] && continue
  if [ "$HAS_RG" -eq 1 ]; then
    HAS_CONFIG_CMD=0
    rg -n --fixed-strings -- "--config ./contracts/runtime/config.example.toml" "$config_doc" >/dev/null && HAS_CONFIG_CMD=1
  else
    HAS_CONFIG_CMD=0
    grep -nF -- "--config ./contracts/runtime/config.example.toml" "$config_doc" >/dev/null && HAS_CONFIG_CMD=1
  fi
  if [ "$HAS_CONFIG_CMD" -ne 1 ]; then
    fail "${config_doc#"$REPO_ROOT"/} is missing a copyable --config example: --config ./contracts/runtime/config.example.toml"
  fi
done < <(require_config_example_docs)

check_command_block() {
  local doc_path="$1"
  local rel_doc="${doc_path#"$REPO_ROOT"/}"
  local in_bash=0
  local line_no=0

  while IFS= read -r raw_line || [ -n "$raw_line" ]; do
    line_no=$((line_no + 1))

    if [ "$raw_line" = '```bash' ]; then
      in_bash=1
      continue
    fi
    if [ "$raw_line" = '```' ]; then
      in_bash=0
      continue
    fi
    if [ "$in_bash" -ne 1 ]; then
      continue
    fi

    local line
    line="$(printf '%s' "$raw_line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    if [ -z "$line" ] || [[ "$line" =~ ^# ]]; then
      continue
    fi

    if [[ "$line" =~ \<[^[:space:]]+\> ]]; then
      fail "$rel_doc:$line_no command contains placeholder text: $line"
    fi

    if [[ "$line" =~ (^|[[:space:]])scripts/[A-Za-z0-9._/-]+ ]]; then
      local bare_script
      if [ "$HAS_RG" -eq 1 ]; then
        bare_script="$(printf '%s\n' "$line" | rg -o '(^|[[:space:]])scripts/[A-Za-z0-9._/-]+' | sed 's/^[[:space:]]*//' | head -n1 || true)"
      else
        bare_script="$(printf '%s\n' "$line" | grep -Eo '(^|[[:space:]])scripts/[A-Za-z0-9._/-]+' | sed 's/^[[:space:]]*//' | head -n1 || true)"
      fi
      if [ -n "$bare_script" ]; then
        fail "$rel_doc:$line_no detected bare scripts/ path; use ./scripts/... or tooling/scripts/... instead: $bare_script"
      fi
    fi

    if [[ "$line" == *"./scripts/"* ]]; then
      local script_rel
      if [ "$HAS_RG" -eq 1 ]; then
        script_rel="$(printf '%s\n' "$line" | rg -o '\./scripts/[A-Za-z0-9._/-]+' | head -n1 || true)"
      else
        script_rel="$(printf '%s\n' "$line" | grep -Eo '\./scripts/[A-Za-z0-9._/-]+' | head -n1 || true)"
      fi
      if [ -n "$script_rel" ] && [ ! -f "$DOC_ROOT/${script_rel#./}" ]; then
        fail "$rel_doc:$line_no script path does not exist: $script_rel"
      fi
    fi

    if [[ "$line" == *"tooling/scripts/"* ]]; then
      local repo_script
      if [ "$HAS_RG" -eq 1 ]; then
        repo_script="$(printf '%s\n' "$line" | rg -o 'tooling/scripts/[A-Za-z0-9._/-]+' | head -n1 || true)"
      else
        repo_script="$(printf '%s\n' "$line" | grep -Eo 'tooling/scripts/[A-Za-z0-9._/-]+' | head -n1 || true)"
      fi
      if [ -n "$repo_script" ] && [ ! -f "$REPO_ROOT/$repo_script" ]; then
        fail "$rel_doc:$line_no script path does not exist: $repo_script"
      fi
    fi

    if [[ "$line" == python\ apps/cli/fileorganize.py* ]] && [ ! -f "$REPO_ROOT/apps/cli/fileorganize.py" ]; then
      fail "$rel_doc:$line_no missing apps/cli/fileorganize.py"
    fi
  done <"$doc_path"
}

while IFS= read -r doc_path; do
  [ -z "$doc_path" ] && continue
  check_command_block "$doc_path"
done < <(list_command_smoke_docs)

if [ "$INSTALL_SMOKE" -eq 1 ]; then
  local_venv="$(governance_runtime_venv_path "$REPO_ROOT")"
  # Keep the packaging smoke mirror outside the repo tree so concurrent
  # governance scans and archive copies never race on repo-local temp paths.
  install_root="${DOCS_SMOKE_INSTALL_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/fileorganize/docs-smoke-install}"
  mkdir -p "$install_root"
  install_tmp="$(mktemp -d "$install_root/docs-smoke.XXXXXX")"
  install_runtime_tmp="$install_tmp/tmp"
  mkdir -p "$install_runtime_tmp"
  build_tmp="$install_tmp/dist"
  source_tmp="$install_tmp/source"
  cleanup_install_tmp() {
    rm -rf -- "$install_tmp"
  }
  trap cleanup_install_tmp EXIT
  install_log="$install_tmp/install-smoke.log"
  prepare_install_smoke_source "$source_tmp"

  if [ -x "$local_venv/bin/python" ]; then
    if ! run_install_smoke_with_existing_venv "$local_venv" "$install_log" "$build_tmp" "$source_tmp" "$install_runtime_tmp"; then
      print_log_tail "$install_log" "existing-venv-install-smoke"
      fail "install smoke failed: reusing the runtime venv did not validate (run bash tooling/runtime/bootstrap_env.sh first)"
    fi
  else
    if ! command -v python3 >/dev/null 2>&1; then
      fail "install smoke requires python3 when no reusable runtime venv is available"
    elif ! TMPDIR="$install_runtime_tmp" TMP="$install_runtime_tmp" TEMP="$install_runtime_tmp" python3 -m venv "$install_tmp/venv"; then
      fail "failed to create the install-smoke venv"
    elif ! TMPDIR="$install_runtime_tmp" TMP="$install_runtime_tmp" TEMP="$install_runtime_tmp" \
      "$install_tmp/venv/bin/python" -m pip install --disable-pip-version-check "$source_tmp" >"$install_log" 2>&1; then
      print_log_tail "$install_log" "temp-venv-install-smoke"
      fail "install smoke failed: pip install could not install the temporary source mirror"
    else
      while IFS= read -r entrypoint; do
        [ -z "$entrypoint" ] && continue
        if ! run_entrypoint_help_smoke "$install_tmp/venv/bin/python" "$install_tmp/venv/bin/${entrypoint}" "$entrypoint" >>"$install_log" 2>&1; then
          print_log_tail "$install_log" "temp-venv-install-smoke"
          fail "install smoke 命令不可用: ${entrypoint} --help"
          break
        fi
      done < <(package_smoke_required_entrypoints "$install_tmp/venv/bin/python")
    fi
  fi
fi

if [ "$fail_count" -gt 0 ]; then
  echo "❌ docs_smoke (command/install docs only): failed $fail_count check(s)" >&2
  exit 1
fi

echo "✅ docs_smoke (command/install docs only): command examples and install smoke passed"
