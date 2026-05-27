import importlib.util
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_a11y_module():
    repo_root = _repo_root()
    script = repo_root / "tooling" / "scripts" / "check_frontend_a11y.py"
    spec = importlib.util.spec_from_file_location("check_frontend_a11y", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_lint_frontend_skips_gemini_without_key_in_local_mode() -> None:
    script = (_repo_root() / "tooling" / "gates" / "lint_frontend.sh").read_text(encoding="utf-8")

    assert "is_ci_context()" in script
    assert "gemini-ui-ux-audit skipped: GEMINI_API_KEY missing in local mode" in script
    assert "GEMINI_API_KEY is required in CI when frontend sources exist" in script


def test_lint_frontend_only_skips_provider_block_in_local_mode() -> None:
    script = (_repo_root() / "tooling" / "gates" / "lint_frontend.sh").read_text(encoding="utf-8")

    assert "is_local_skippable_gemini_error()" in script
    assert "transient/provider issue in local mode" in script
    assert "DEADLINE_EXCEEDED" in script
    assert "CANCELLED" in script
    assert "gemini-ui-ux-audit failed in CI" in script


def test_lint_frontend_keeps_canonical_container_path_even_during_host_emergency_gate() -> None:
    script = (_repo_root() / "tooling" / "gates" / "lint_frontend.sh").read_text(encoding="utf-8")

    assert "LINT_FRONTEND_ALLOW_HOST_EXECUTION" in script
    assert "canonical frontend verification stays containerized by default" in script
    assert ('env -u FILEORGANIZE_ALLOW_HOST_EXECUTION FILEORGANIZE_COMPOSE_SERVICE=fileorganize-web-api bash "$ROOT/scripts/container_exec.sh"') in script


def test_lint_frontend_cleanup_is_best_effort_for_node_modules_permissions() -> None:
    script = (_repo_root() / "tooling" / "gates" / "lint_frontend.sh").read_text(encoding="utf-8")

    assert "cleanup_host_webui_mountpoint()" in script
    assert "volume-release timing during post-run cleanup" in script
    assert 'find "$REPO_ROOT/apps/webui/node_modules" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true' in script
    assert 'rmdir "$REPO_ROOT/apps/webui/node_modules" 2>/dev/null || true' in script


def test_run_webui_task_allows_explicit_host_execution_outside_ci() -> None:
    script = (_repo_root() / "tooling" / "runtime" / "run_webui_task.sh").read_text(encoding="utf-8")

    assert "is_ci_context()" in script
    assert "emergency host execution enabled; canonical webui task path stays containerized by default" in script
    assert "FILEORGANIZE_ALLOW_HOST_EXECUTION=1 is forbidden in CI" in script


def test_run_webui_task_retries_after_node_modules_residue() -> None:
    script = (_repo_root() / "tooling" / "runtime" / "run_webui_task.sh").read_text(encoding="utf-8")

    assert "node_modules cleanup left residue; continuing with install retry path" in script
    assert "npm ci retrying after hard reset of node_modules" in script
    assert 'echo "❌ [webui-task] apps/webui/package-lock.json is required for deterministic installs" >&2' in script
    assert "webui-node-modules-stale-$$" in script
    assert 'if mv "$target" "$quarantine" 2>/dev/null; then' in script
    assert 'find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true' in script
    assert 'npm --prefix "$REPO_ROOT/apps/webui" exec vite -- --version >/dev/null 2>&1' in script


def test_run_webui_task_handles_empty_extra_args_under_set_u() -> None:
    script = (_repo_root() / "tooling" / "runtime" / "run_webui_task.sh").read_text(encoding="utf-8")

    assert 'if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then' in script
    assert 'exec npm --prefix "$REPO_ROOT/apps/webui" run "$script_name"' in script


def test_run_webui_task_forwards_skip_install_into_container_command() -> None:
    script = (_repo_root() / "tooling" / "runtime" / "run_webui_task.sh").read_text(encoding="utf-8")
    expected = (
        'env FILEORGANIZE_COMPOSE_SERVICE=fileorganize-web-api bash "$ROOT/scripts/container_exec.sh" --label "webui-${TASK}" -- "${CONTAINER_ARGS[@]}"'
    )

    assert 'CONTAINER_ARGS=(bash tooling/runtime/run_webui_task.sh "$TASK")' in script
    assert 'if [ "$SKIP_INSTALL" = "1" ]; then' in script
    assert "CONTAINER_ARGS+=(--skip-install)" in script
    assert expected in script


def test_run_webui_task_keeps_skip_install_builds_in_one_container_session() -> None:
    script = (_repo_root() / "tooling" / "runtime" / "run_webui_task.sh").read_text(encoding="utf-8")

    assert "join_shell_command()" in script
    assert 'CONTAINER_INSTALL_COMMAND="$(join_shell_command bash tooling/runtime/run_webui_task.sh ci-install)"' in script
    assert 'CONTAINER_TASK_COMMAND=(bash tooling/runtime/run_webui_task.sh "$TASK" --skip-install)' in script
    assert 'CONTAINER_SKIP_INSTALL_COMMAND="$(join_shell_command "${CONTAINER_TASK_COMMAND[@]}")"' in script
    assert 'bash -lc "${CONTAINER_INSTALL_COMMAND} && ${CONTAINER_SKIP_INSTALL_COMMAND}"' in script


def test_lint_frontend_dependency_health_check_verifies_eslint_cli_startup() -> None:
    script = (_repo_root() / "tooling" / "gates" / "lint_frontend.sh").read_text(encoding="utf-8")

    assert 'echo "❌ [lint_frontend] apps/webui/package-lock.json is required for deterministic installs" >&2' in script
    assert "npm-ci-webui retrying after hard reset of node_modules" in script
    assert 'npm --prefix "$REPO_ROOT/apps/webui" ls --depth=0 >/dev/null 2>&1 || return 1' in script
    assert 'npm --prefix "$REPO_ROOT/apps/webui" exec eslint -- --version >/dev/null 2>&1' in script


def test_quality_gate_postflight_prunes_repo_runtime_before_residue_checks() -> None:
    script = (_repo_root() / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")
    root_clean_cmd = '"$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_root_clean_after_mainflows.py" --root "$REPO_ROOT"'

    assert 'bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT" >/dev/null 2>&1 || true' in script
    postflight_idx = script.index("run_postflight_runtime_hygiene() {")
    prune_idx = script.index('bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT" >/dev/null 2>&1 || true', postflight_idx)
    root_clean_idx = script.index(root_clean_cmd, postflight_idx)

    assert prune_idx < root_clean_idx


def test_quality_gate_preflight_prunes_repo_runtime_before_runtime_budget_checks() -> None:
    script = (_repo_root() / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")
    marker = (
        "# Keep runtime cleanliness checks out of the parallel preflight fan-out.\n"
        "  # Frontend/doc short-checks can transiently materialize `apps/webui/node_modules`"
    )
    runtime_layout_cmd = (
        '("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_layout.py" --root "$REPO_ROOT" 2>&1 | tee "$runtime_layout_log")'
    )

    section_idx = script.index(marker)
    prune_idx = script.index('bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT" >/dev/null 2>&1 || true', section_idx)
    runtime_layout_idx = script.index(runtime_layout_cmd, section_idx)

    assert prune_idx < runtime_layout_idx


def test_container_exec_bootstrap_separates_hash_locked_and_dev_installs() -> None:
    script = (_repo_root() / "tooling" / "scripts" / "container_exec.sh").read_text(encoding="utf-8")
    pip_lock_install = (
        '"$venv_dir/bin/python" -m pip install --disable-pip-version-check --require-hashes -r tooling/requirements-pip.lock.txt'
    )

    assert "bootstrap_setuptools_from_dev_lock()" in script
    assert "tooling/requirements-dev.lock.txt is missing a setuptools pin" in script
    assert pip_lock_install in script
    assert '"$venv_dir/bin/python" -m pip install --require-hashes -r tooling/requirements.lock.txt' in script
    assert 'bootstrap_setuptools_from_dev_lock "$venv_dir/bin/python"' in script
    assert '"$venv_dir/bin/python" -m pip install --require-hashes -r tooling/requirements-dev.lock.txt' in script
    assert '"$venv_dir/bin/python" -m pip install -r requirements-dev.txt' not in script
    assert '"$venv_dir/bin/python" -m pip install -r requirements.lock.txt -r requirements-dev.txt' not in script


def test_container_exec_restores_prebuilt_venv_before_creating_runtime_venv() -> None:
    script = (_repo_root() / "tooling" / "scripts" / "container_exec.sh").read_text(encoding="utf-8")

    restore_idx = script.index('if [ "$prebuilt_hash" = "$req_hash" ]; then')
    venv_create_idx = script.index('recreate_runtime_venv "$venv_dir"')

    assert restore_idx < venv_create_idx


def test_container_exec_prebuilt_restore_hard_resets_runtime_venv() -> None:
    script = (_repo_root() / "tooling" / "scripts" / "container_exec.sh").read_text(encoding="utf-8")

    assert 'RESTORE_TREE_HELPER="$ROOT/scripts/restore_prebuilt_tree.py"' in script
    assert 'RESTORE_TREE_HELPER="${RESTORE_TREE_HELPER:-/workspace/tooling/scripts/restore_prebuilt_tree.py}"' in script
    assert 'python3 "$RESTORE_TREE_HELPER" --src "$prebuilt_venv_dir" --dst "$venv_dir"' in script
    assert 'python -m venv "$venv_dir" --clear' not in script
    assert 'rm -rf "$target"' not in script
    assert 'find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf {} +' in script
    assert 'python -m venv "$target"' in script


def test_bootstrap_env_restores_prebuilt_venv_before_creating_runtime_venv() -> None:
    script = (_repo_root() / "tooling" / "runtime" / "bootstrap_env.sh").read_text(encoding="utf-8")

    restore_idx = script.index('if ! restore_prebuilt_venv_if_available "$req_hash"; then')
    venv_create_idx = script.index('recreate_runtime_venv "$VENV_PATH"')

    assert restore_idx < venv_create_idx


def test_bootstrap_env_prebuilt_restore_clears_existing_runtime_venv_contents() -> None:
    script = (_repo_root() / "tooling" / "runtime" / "bootstrap_env.sh").read_text(encoding="utf-8")
    pip_lock_install = (
        '"$PYTHON_BIN" -m pip install --disable-pip-version-check --require-hashes -r "$REPO_ROOT/tooling/requirements-pip.lock.txt"'
    )

    assert 'RESTORE_TREE_HELPER="$ROOT/scripts/restore_prebuilt_tree.py"' in script
    assert 'python3 "$RESTORE_TREE_HELPER" --src "$prebuilt_dir" --dst "$VENV_PATH"' in script
    assert pip_lock_install in script
    assert 'python3 -m venv "$VENV_PATH" --clear' not in script
    assert 'rm -rf "$target"' not in script
    assert 'find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf {} +' in script
    assert 'python3 -m venv "$target"' in script


def test_requirements_pip_lock_keeps_pip_at_or_above_the_current_security_floor() -> None:
    lock = (_repo_root() / "tooling" / "requirements-pip.lock.txt").read_text(encoding="utf-8")

    assert "pip==26.0.1" in lock
    assert "pip==25.0.1" not in lock


def test_restore_prebuilt_tree_replaces_existing_contents_without_file_exists_conflicts(tmp_path: Path) -> None:
    script = _repo_root() / "tooling" / "scripts" / "restore_prebuilt_tree.py"
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "bin").mkdir(parents=True)
    (src / "lib" / "pkg").mkdir(parents=True)
    (src / "bin" / "python").write_text("fresh", encoding="utf-8")
    (src / "lib" / "pkg" / "module.py").write_text("fresh", encoding="utf-8")

    (dst / "bin").mkdir(parents=True)
    (dst / "lib").mkdir(parents=True)
    (dst / "bin" / "python").write_text("stale", encoding="utf-8")
    (dst / "lib" / "pkg").write_text("wrong-type", encoding="utf-8")

    subprocess.run(["python3", str(script), "--src", str(src), "--dst", str(dst)], check=True)

    assert (dst / "bin" / "python").read_text(encoding="utf-8") == "fresh"
    assert (dst / "lib" / "pkg" / "module.py").read_text(encoding="utf-8") == "fresh"

    subprocess.run(["python3", str(script), "--src", str(src), "--dst", str(dst)], check=True)

    assert (dst / "bin" / "python").read_text(encoding="utf-8") == "fresh"
    assert (dst / "lib" / "pkg" / "module.py").read_text(encoding="utf-8") == "fresh"


def test_check_frontend_a11y_treats_native_button_and_design_system_button_differently(tmp_path: Path) -> None:
    mod = _load_a11y_module()
    design_system_file = tmp_path / "design-system.tsx"
    design_system_file.write_text("<Button>保存</Button>\n", encoding="utf-8")
    native_button_file = tmp_path / "native.tsx"
    native_button_file.write_text("<button>保存</button>\n", encoding="utf-8")

    assert mod._check_file(design_system_file) == []
    issues = mod._check_file(native_button_file)
    assert any("button missing explicit type" in issue for issue in issues)


def test_env_contract_registers_web_stack_runtime_vars() -> None:
    registry = (_repo_root() / "contracts" / "runtime" / "env_contract_registry.yaml").read_text(encoding="utf-8")

    assert "FILEORGANIZE_WEBUI_HOST" in registry
    assert "FILEORGANIZE_WEBUI_PORT" in registry
    assert "FILEORGANIZE_WEB_API_HOST" in registry
    assert "FILEORGANIZE_WEB_API_PORT" in registry


def test_env_contract_registers_live_coverage_runtime_vars() -> None:
    registry = (_repo_root() / "contracts" / "runtime" / "env_contract_registry.yaml").read_text(encoding="utf-8")
    env_example = (_repo_root() / ".env.example").read_text(encoding="utf-8")

    assert "FILEORGANIZE_LIVE_COVERAGE_FILE" in registry
    assert "LIVE_COVERAGE_FILE" in registry
    assert "FILEORGANIZE_LIVE_COVERAGE_FILE=" in env_example
    assert "LIVE_COVERAGE_FILE=" in env_example
