import json
import re
from pathlib import Path

import yaml  # type: ignore[import-untyped]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _assert_contains(text: str, needle: str, hint: str) -> None:
    assert needle in text, f"{hint}: missing {needle!r}"


def _load_ci_local_body() -> str:
    package_json = json.loads((_repo_root() / "package.json").read_text(encoding="utf-8"))
    ci_local = package_json["scripts"]["ci:local"]
    wrapper = "bash tooling/gates/ci_local.sh"
    if ci_local == wrapper:
        return (_repo_root() / "tooling" / "gates" / "ci_local.sh").read_text(encoding="utf-8")
    return ci_local


def _load_governance_defaults() -> dict[str, str]:
    defaults_path = _repo_root() / "contracts" / "governance" / "governance.defaults.env"
    values: dict[str, str] = {}
    for raw_line in defaults_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _extract_mutation_manual_test_paths(workflow_text: str) -> set[str]:
    paths: set[str] = set()
    for line in workflow_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("tests:"):
            paths.update(stripped.removeprefix("tests:").strip().split())
    return paths


def _load_env_registry() -> dict[str, object]:
    registry_path = _repo_root() / "contracts" / "runtime" / "env_contract_registry.yaml"
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), "env_contract_registry.yaml must be a mapping"
    return payload


def _extract_contract_vars_from_registry() -> set[str]:
    registry = _load_env_registry()
    sections_raw = registry.get("sections", {})
    assert isinstance(sections_raw, dict), "registry sections must be a mapping"
    sections = sections_raw
    values: set[str] = set()
    for names in sections.values():
        assert isinstance(names, list), "registry sections must be lists"
        values.update(str(name) for name in names)
    return values


def _extract_category_budgets_from_registry() -> dict[str, int]:
    registry = _load_env_registry()
    budgets_raw = registry.get("category_budgets", {})
    assert isinstance(budgets_raw, dict), "registry budgets must be a mapping"
    budgets = budgets_raw
    return {str(name): int(limit) for name, limit in budgets.items()}


def _extract_contract_vars_from_doc(env_doc: str) -> set[str]:
    # Keep only env-like tokens that belong to this repo's contract namespaces.
    allowed_prefixes = (
        "FILEYARD_",
        "GEMINI_",
        "LIVE_",
        "CLEAN_CACHE_",
        "SECRET_SCAN_",
        "UPGRADE_DEPS_",
        "GENERATE_REPORT_",
        "PRE_COMMIT_",
        "PYTEST_",
        "HEARTBEAT_",
        "QUALITY_GATE_",
        "CONFIDENCE_",
    )
    tokens = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", env_doc))
    return {
        token
        for token in tokens
        if token.startswith(allowed_prefixes) and not token.endswith("_") and not re.fullmatch(r"[A-Z_]+_\d+", token)
    }


def test_mutation_canary_gate_is_in_pre_push_and_ci() -> None:
    """Mutation canary is now in pre-push (strict mode) and CI, not pre-commit.

    Design rationale: Pre-commit should complete in <15s for fast feedback.
    Mutation canary is a heavier check that belongs in pre-push or CI.
    """
    repo_root = _repo_root()
    pre_push_gate = (repo_root / "tooling" / "gates" / "pre_push_gate.sh").read_text(encoding="utf-8")
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    _assert_contains(
        pre_push_gate,
        "mutation-canary",
        "pre-push mutation gate step",
    )
    _assert_contains(
        pre_push_gate,
        "check_mutation_canary.py",
        "pre-push mutation canary command",
    )
    _assert_contains(
        ci,
        "--json-output .runtime-cache/logs/mutation-canary-summary.json",
        "mutation canary json summary artifact",
    )
    _assert_contains(ci, "name: Mutation canary gate", "CI mutation gate step")


def test_mutation_manual_workflow_covers_core_python_modules() -> None:
    repo_root = _repo_root()
    workflow_text = (repo_root / ".github" / "workflows" / "mutation-manual.yml").read_text(encoding="utf-8")

    _assert_contains(workflow_text, "name: mutation-manual", "manual mutation workflow header")
    _assert_contains(workflow_text, "python-mutmut:", "manual mutmut job")
    _assert_contains(workflow_text, "matrix:", "manual mutmut matrix")
    _assert_contains(workflow_text, "max-parallel: 3", "manual mutmut parallelism cap")

    for module, mutate_path in (
        ("core_utils", "packages/domain/core_utils.py"),
        ("manifest_store", "packages/infrastructure/manifest_store.py"),
        ("config_loader", "packages/infrastructure/config_loader.py"),
        ("apply_command", "packages/application/apply_command.py"),
        ("pipeline_config", "packages/domain/pipeline_config.py"),
        ("cli_app", "apps/cli/cli_app.py"),
        ("gemini_client", "packages/infrastructure/gemini_client.py"),
        ("logging_utils", "packages/observability/logging_utils.py"),
        ("analyze_media", "packages/application/analyze_media.py"),
        ("reporting", "packages/application/reporting.py"),
    ):
        _assert_contains(workflow_text, f"module: {module}", f"manual mutmut module {module}")
        _assert_contains(workflow_text, f"mutate_path: {mutate_path}", f"manual mutmut path {mutate_path}")

    _assert_contains(workflow_text, "check_mutation_report.py", "manual mutmut structured fail gate")
    _assert_contains(workflow_text, "--max-survived 0", "manual mutmut survived threshold")
    _assert_contains(workflow_text, "--max-timed-out 0", "manual mutmut timed_out threshold")
    _assert_contains(workflow_text, "--max-suspicious 0", "manual mutmut suspicious threshold")
    _assert_contains(workflow_text, "--min-killed 1", "manual mutmut min killed threshold")
    _assert_contains(workflow_text, "--require-non-empty-sample", "manual mutmut non-empty sample threshold")
    _assert_contains(workflow_text, "mutation-manual-diagnostics-${{ matrix.module }}", "manual mutmut per-module artifacts")

    test_paths = _extract_mutation_manual_test_paths(workflow_text)
    assert test_paths, "manual mutation workflow must define at least one tests: path"
    for test_path in test_paths:
        assert (repo_root / test_path).exists(), f"manual mutation tests path missing: {test_path}"


def test_mutation_manual_workflow_uses_hash_locked_mutmut_install() -> None:
    workflow_text = (_repo_root() / ".github" / "workflows" / "mutation-manual.yml").read_text(encoding="utf-8")
    dev_shell = (_repo_root() / "tooling" / "requirements-dev.txt").read_text(encoding="utf-8")
    dev_lock = (_repo_root() / "tooling" / "requirements-dev.lock.txt").read_text(encoding="utf-8")

    _assert_contains(workflow_text, "name: mutation-image-contract", "manual mutation image contract artifact")
    _assert_contains(workflow_text, "Load CI runtime image from contract", "manual mutation image contract load step")
    _assert_contains(workflow_text, 'echo "FILEYARD_CI_IMAGE=$IMAGE_REF" >> "$GITHUB_ENV"', "manual image env export")
    _assert_contains(
        workflow_text,
        "bash tooling/scripts/container_exec.sh --label mutation-manual --",
        "manual mutation run via container_exec",
    )
    _assert_contains(
        workflow_text,
        "bash tooling/scripts/container_exec.sh --label mutation-manual-report --",
        "manual mutation report via container_exec",
    )
    _assert_contains(dev_shell, "-r requirements-dev.lock.txt", "dev shell forwards to dev lock")
    _assert_contains(dev_lock, "mutmut==2.5.1", "dev lock includes mutmut pin")
    assert "actions/setup-python" not in workflow_text, "manual workflow should rely on image contract instead of host python bootstrap"


def test_quality_gate_runs_fast_lane_before_full_pytest() -> None:
    quality_gate = (_repo_root() / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")

    fast_lane = re.compile(r"run_step_with_heartbeat\s+\\\s*pytest-fast\s+\\\s*run_pytest_with_isolated_tmp", re.MULTILINE)
    pre_mutation_hygiene = re.compile(r"run_step\s+pre-mutation-cache-hygiene\s+run_post_mutation_cache_hygiene", re.MULTILINE)
    post_mutation_hygiene = re.compile(r"run_step\s+post-mutation-cache-hygiene\s+run_post_mutation_cache_hygiene", re.MULTILINE)
    full_lane_pattern = (
        r"run_step_with_heartbeat\s+\\\s*pytest\s+\\\s*run_pytest_with_isolated_tmp"
        r"\s+\\\s*env -u PRE_COMMIT_FROM_REF -u PRE_COMMIT_TO_REF FILEYARD_RUN_LIVE_TESTS=0"
    )
    full_lane = re.compile(full_lane_pattern, re.MULTILINE)
    mutation_gate = "run_step mutation-canary"

    fast_match = fast_lane.search(quality_gate)
    fast_idx = -1 if fast_match is None else fast_match.start()
    mutation_idx = quality_gate.find(mutation_gate)
    pre_mutation_hygiene_match = pre_mutation_hygiene.search(quality_gate)
    pre_mutation_hygiene_idx = -1 if pre_mutation_hygiene_match is None else pre_mutation_hygiene_match.start()
    post_mutation_hygiene_match = post_mutation_hygiene.search(quality_gate)
    post_mutation_hygiene_idx = -1 if post_mutation_hygiene_match is None else post_mutation_hygiene_match.start()
    full_match = full_lane.search(quality_gate)
    full_idx = -1 if full_match is None else full_match.start()

    assert fast_idx != -1, "quality_gate missing pytest-fast step"
    assert mutation_idx != -1, "quality_gate missing mutation-canary step"
    assert pre_mutation_hygiene_idx != -1, "quality_gate missing pre-mutation cache hygiene step"
    assert post_mutation_hygiene_idx != -1, "quality_gate missing post-mutation cache hygiene step"
    assert full_idx != -1, "quality_gate missing full pytest step"
    assert fast_idx < full_idx, "quality_gate must run pytest-fast before full pytest"
    assert fast_idx < pre_mutation_hygiene_idx < mutation_idx, "quality_gate must clear pytest-fast residue before mutation canary"
    assert mutation_idx < post_mutation_hygiene_idx < full_idx, "quality_gate must clear mutation residue before full pytest"
    _assert_contains(quality_gate, 'bash "$ROOT/cleanup/prune_machine_cache.sh" --safe', "quality_gate safe machine pycache cleanup")
    _assert_contains(
        quality_gate,
        'bash "$ROOT/cleanup/prune_repo_runtime.sh" "$REPO_ROOT"',
        "quality_gate repo runtime cleanup after mutation",
    )
    _assert_contains(quality_gate, "--cov-branch", "quality_gate branch coverage collection")
    _assert_contains(quality_gate, "--strict-config", "quality_gate strict pytest config")
    _assert_contains(quality_gate, "--strict-markers", "quality_gate strict pytest markers")


def test_change_detection_uses_shared_detection_and_resolution_helpers() -> None:
    ci = (_repo_root() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    detect_helper = (_repo_root() / "tooling" / "ci" / "detect_change_scope.sh").read_text(encoding="utf-8")
    resolve_helper = (_repo_root() / "tooling" / "ci" / "resolve_change_detection_gate.sh").read_text(encoding="utf-8")

    assert ci.count("bash tooling/ci/detect_change_scope.sh .github/.ci_changed_files.txt") >= 2
    _assert_contains(ci, "bash tooling/ci/resolve_change_detection_gate.sh", "change-detection resolver helper")
    _assert_contains(detect_helper, "check_change_detection_scope.py", "change-detection scope check")
    _assert_contains(resolve_helper, "run-heavy=${primary_heavy}", "resolver emits primary heavy output")
    _assert_contains(resolve_helper, "changed-count=${fallback_count}", "resolver emits fallback change count")


def test_quality_gate_enforces_fail_fast_after_each_major_stage() -> None:
    quality_gate = (_repo_root() / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")

    _assert_contains(quality_gate, "fail-fast after preflight-checks", "quality_gate fail-fast preflight")
    _assert_contains(quality_gate, "fail-fast after pytest-fast", "quality_gate fail-fast pytest-fast")
    _assert_contains(quality_gate, "fail-fast after pre-mutation-cache-hygiene", "quality_gate fail-fast pre-mutation cache hygiene")
    _assert_contains(quality_gate, "fail-fast after mutation-canary", "quality_gate fail-fast mutation")
    _assert_contains(quality_gate, "fail-fast after post-mutation-cache-hygiene", "quality_gate fail-fast post-mutation cache hygiene")
    _assert_contains(quality_gate, "fail-fast after pytest", "quality_gate fail-fast full pytest")
    _assert_contains(quality_gate, "fail-fast after coverage-threshold", "quality_gate fail-fast coverage")
    _assert_contains(quality_gate, "fail-fast after static-checks", "quality_gate fail-fast static checks")
    _assert_contains(quality_gate, "fail-fast after pip-audit", "quality_gate fail-fast pip audit")
    _assert_contains(quality_gate, "fail-fast after post-summary-governance", "quality_gate fail-fast post-summary-governance")
    _assert_contains(quality_gate, "--min-branch 70", "quality_gate branch coverage threshold")


def test_quality_gate_treats_pip_audit_bootstrap_tls_failures_as_fallback_eligible() -> None:
    quality_gate = (_repo_root() / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")

    _assert_contains(quality_gate, "Failed to install packages", "pip-audit bootstrap failure fallback keyword")
    _assert_contains(quality_gate, "TLS CA certificate bundle", "pip-audit TLS cert fallback keyword")
    _assert_contains(quality_gate, "build_pip_audit_ignore_args dev-lock-only", "pip-audit allowlist helper")
    _assert_contains(quality_gate, "--strict --no-deps --disable-pip", "pip-audit dev fallback command prefix")
    _assert_contains(quality_gate, "tooling/requirements-dev.lock.txt", "pip-audit dev fallback target lockfile")


def test_quality_gate_defers_receipt_driven_checks_until_after_summary_write() -> None:
    quality_gate = (_repo_root() / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")

    preflight_banner = re.search(r'echo "=== \[quality_gate\] preflight-checks \(parallel: (?P<body>.+)\) ==="', quality_gate)
    post_summary_idx = quality_gate.find("run_step post-summary-governance run_post_summary_governance_checks")
    write_summary_match = re.search(r"write_gate_summary pass\s+run_step post-summary-governance", quality_gate)
    post_summary_impl_idx = quality_gate.find("run_post_summary_governance_checks()")

    assert preflight_banner is not None
    assert post_summary_idx != -1
    assert write_summary_match is not None
    assert post_summary_impl_idx != -1
    preflight_body = preflight_banner.group("body")
    assert "upstream-freshness" not in preflight_body
    assert "upstream-receipts" not in preflight_body
    assert "gate-log-correlation" not in preflight_body
    assert quality_gate.find('check_upstream_verification_freshness.py" --root "$REPO_ROOT"', post_summary_impl_idx) != -1
    assert quality_gate.find('check_upstream_receipts.py" --root "$REPO_ROOT"', post_summary_impl_idx) != -1
    assert quality_gate.find('check_gate_log_correlation.py" \\', post_summary_impl_idx) != -1
    assert 'generate_ci_evidence_bundle.py" \\\n    --artifacts-root "$REPO_ROOT/.runtime-cache"' in quality_gate
    assert 'bash "$ROOT/upstreams/refresh_receipts.sh" --bundle "$evidence_bundle"' in quality_gate


def test_local_ci_script_bootstraps_webui_deps_before_frontend_checks() -> None:
    ci_local = _load_ci_local_body()

    install_idx = ci_local.find("bash tooling/runtime/run_webui_task.sh ci-install")
    lint_idx = ci_local.find("bash tooling/gates/lint_frontend.sh")
    test_idx = ci_local.find("bash tooling/runtime/run_webui_task.sh test")
    build_idx = ci_local.find("bash tooling/runtime/run_webui_task.sh build")

    assert install_idx != -1, "ci:local must install webui dependencies before frontend verification"
    assert lint_idx != -1, "ci:local must run frontend lint checks"
    assert test_idx != -1, "ci:local must run webui tests"
    assert build_idx != -1, "ci:local must run webui build"
    assert install_idx < lint_idx < test_idx < build_idx


def test_root_workspace_scripts_use_governed_webui_wrappers() -> None:
    package_json = json.loads((_repo_root() / "package.json").read_text(encoding="utf-8"))
    scripts = package_json["scripts"]

    assert scripts["dev"] == "bash tooling/runtime/run_webui.sh"
    assert scripts["build"] == "bash tooling/runtime/run_webui_task.sh build"
    assert scripts["lint"] == "bash tooling/runtime/run_webui_task.sh lint"
    assert scripts["lint:frontend"] == "bash tooling/runtime/run_webui_task.sh lint"
    assert scripts["test"] == "bash tooling/runtime/run_webui_task.sh test"
    assert scripts["upstreams:refresh-receipts"] == "bash tooling/upstreams/refresh_receipts.sh"
    assert scripts["upstreams:import-receipts"] == "bash tooling/upstreams/import_receipts.sh"


def test_live_runner_caps_retry_and_retries_only_network_timeout() -> None:
    run_live = (_repo_root() / "tooling" / "runtime" / "run_live_tests.sh").read_text(encoding="utf-8")
    _assert_contains(run_live, 'LIVE_MAX_RETRIES "2"', "live retry default")
    _assert_contains(run_live, '[ "${LIVE_MAX_RETRIES}" -gt 2 ]', "live retry clamp")
    _assert_contains(
        run_live,
        'if ! is_retryable_live_failure_class "$failure_class" || [ "$attempt" -ge "${LIVE_MAX_RETRIES}" ]; then',
        "live retry classification gate",
    )
    _assert_contains(run_live, "is_retryable_live_failure_class()", "live retry helper function")
    _assert_contains(run_live, "live retry backoff", "live retry backoff observability")
    _assert_contains(run_live, 'grep -Eqi "LIVE_ERROR_CLASS=business', "live fallback business classification is case-insensitive")
    _assert_contains(
        run_live,
        'grep -Eqi "LIVE_ERROR_CLASS=network-timeout',
        "live fallback network classification is case-insensitive",
    )
    _assert_contains(
        run_live,
        'grep -Eqi "LIVE_ERROR_CLASS=network-jitter',
        "live fallback network jitter classification is case-insensitive",
    )


def test_live_runner_heartbeat_includes_progress() -> None:
    run_live = (_repo_root() / "tooling" / "runtime" / "run_live_tests.sh").read_text(encoding="utf-8")
    _assert_contains(run_live, "[live-heartbeat]", "live heartbeat marker")
    _assert_contains(run_live, "progress=%s", "live heartbeat progress payload")
    _assert_contains(run_live, 'current_progress="(no-output-yet)"', "live heartbeat empty-progress fallback")
    _assert_contains(run_live, "--strict-config", "live runner strict pytest config")
    _assert_contains(run_live, "--strict-markers", "live runner strict pytest markers")


def test_live_tests_include_real_preflight_and_teardown_contract() -> None:
    llm_test = (_repo_root() / "tests" / "e2e" / "test_live_llm_integration.py").read_text(encoding="utf-8")
    browser_test = (_repo_root() / "tests" / "e2e" / "test_live_external_site_playwright.py").read_text(encoding="utf-8")

    _assert_contains(llm_test, "LIVE_MAX_RETRIES = 2", "live llm retry cap")
    _assert_contains(browser_test, "LIVE_MAX_RETRIES = 2", "live browser retry cap")
    _assert_contains(llm_test, "@pytest.mark.live_llm", "live llm marker")
    _assert_contains(browser_test, "@pytest.mark.live_browser", "live browser marker")
    _assert_contains(llm_test, "def live_cleanup_actions()", "live llm teardown fixture")
    _assert_contains(browser_test, "def live_cleanup_actions()", "live browser teardown fixture")
    _assert_contains(llm_test, "assert not live_cleanup_actions", "live llm teardown registration policy")
    _assert_contains(browser_test, "assert not live_cleanup_actions", "live browser teardown registration policy")


def test_pre_commit_wires_lightweight_gates_only() -> None:
    """Pre-commit should only contain lightweight checks (<15s total).

    Heavy checks like lint-backend, placebo-assertion-gate, and a11y
    are moved to pre-push or CI for better developer experience.
    """
    precommit = (_repo_root() / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    _assert_contains(precommit, "ruff", "pre-commit ruff formatting")
    _assert_contains(precommit, "gitleaks", "pre-commit gitleaks security")
    _assert_contains(precommit, "detect-secrets", "pre-commit detect-secrets")
    _assert_contains(precommit, "stages: [pre-commit]", "pre-commit stage declaration")
    _assert_contains(precommit, "stages: [pre-push]", "pre-push stage declaration")
    _assert_contains(precommit, "local-pre-push-gate", "pre-push gate hook")


def test_ci_wires_semantic_ui_ux_audit_step() -> None:
    ci = (_repo_root() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    _assert_contains(ci, "Semantic UI/UX audit gate (Gemini)", "CI semantic ui audit step")
    _assert_contains(ci, "gemini_ui_ux_audit.py", "CI semantic ui audit command")
    _assert_contains(ci, "GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}", "CI semantic ui audit secret wiring")
    _assert_contains(ci, "vars.GEMINI_UI_AUDIT_MODEL", "CI semantic ui audit variable wiring")


def test_write_before_search_gate_is_wired_into_quality_and_ci() -> None:
    repo_root = _repo_root()
    test_quality_gate = (repo_root / "tooling" / "gates" / "test_quality_gate.sh").read_text(encoding="utf-8")
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    _assert_contains(
        test_quality_gate,
        "check_write_before_search.py",
        "test_quality_gate write-before-search command",
    )
    _assert_contains(ci, "ci-write-before-search", "CI write-before-search gate label")
    _assert_contains(ci, "check_write_before_search.py", "CI write-before-search command")


def test_doc_drift_and_no_logs_gates_are_wired_into_quality_and_ci() -> None:
    repo_root = _repo_root()
    quality_gate = (repo_root / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")
    local_quality_gate = (repo_root / "tooling" / "gates" / "local_quality_gate.sh").read_text(encoding="utf-8")
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    _assert_contains(
        quality_gate,
        "check_doc_drift.py",
        "quality_gate doc-drift command",
    )
    _assert_contains(quality_gate, "check_docs_scope.py", "quality_gate docs-scope command")
    _assert_contains(quality_gate, "check_docs_manual_facts.py", "quality_gate docs-manual-facts command")
    _assert_contains(quality_gate, "check_docs_ssot_hash.py", "quality_gate docs-ssot-hash command")
    _assert_contains(quality_gate, "check_docs_render_state.py", "quality_gate docs render state command")
    _assert_contains(
        quality_gate,
        "check_no_logs_no_merge.py",
        "quality_gate no-logs-no-merge command",
    )
    _assert_contains(ci, "ci-doc-drift", "CI doc-drift gate label")
    _assert_contains(ci, "check_doc_drift.py", "CI doc-drift gate command")
    _assert_contains(ci, "ci-docs-scope", "CI docs-scope gate label")
    _assert_contains(ci, "check_docs_scope.py", "CI docs-scope gate command")
    _assert_contains(ci, "ci-docs-manual-facts", "CI docs-manual-facts gate label")
    _assert_contains(ci, "check_docs_manual_facts.py", "CI docs-manual-facts gate command")
    _assert_contains(ci, "ci-docs-ssot-hash", "CI docs-ssot-hash gate label")
    _assert_contains(ci, "check_docs_ssot_hash.py", "CI docs-ssot-hash gate command")
    _assert_contains(ci, "ci-docs-render-state", "CI docs render state gate label")
    _assert_contains(ci, "check_docs_render_state.py", "CI docs render state gate command")
    _assert_contains(local_quality_gate, "check_docs_scope.py", "local fast docs-scope gate")
    _assert_contains(local_quality_gate, "check_docs_manual_facts.py", "local fast docs-manual-facts gate")
    _assert_contains(local_quality_gate, "check_docs_ssot_hash.py", "local fast docs-ssot-hash gate")
    _assert_contains(local_quality_gate, "check_docs_render_state.py", "local fast docs render state gate")
    _assert_contains(ci, "ci-no-logs-no-merge", "CI no-logs gate label")
    _assert_contains(ci, "check_no_logs_no_merge.py", "CI no-logs gate command")


def test_local_fast_and_standard_prepush_align_with_ci_core_gates() -> None:
    repo_root = _repo_root()
    local_quality_gate = (repo_root / "tooling" / "gates" / "local_quality_gate.sh").read_text(encoding="utf-8")
    pre_push_gate = (repo_root / "tooling" / "gates" / "pre_push_gate.sh").read_text(encoding="utf-8")

    _assert_contains(local_quality_gate, "check_no_logs_no_merge.py", "local fast no-logs gate")
    _assert_contains(local_quality_gate, "check_write_before_search.py", "local fast write-before-search gate")
    _assert_contains(local_quality_gate, "check_required_checks_matrix.py", "local fast required-checks gate")
    _assert_contains(local_quality_gate, "check_docs_scope.py", "local fast docs-scope gate")
    _assert_contains(local_quality_gate, "check_docs_manual_facts.py", "local fast docs-manual-facts gate")
    _assert_contains(local_quality_gate, "--strict-config --strict-markers", "local fast strict pytest flags")
    _assert_contains(
        pre_push_gate,
        'exec bash "$ROOT/scripts/container_exec.sh" --label pre-push-gate -- bash tooling/gates/pre_push_gate.sh "$@"',
        "pre-push delegates to container_exec by default",
    )
    _assert_contains(
        pre_push_gate,
        'step prepush-lite bash "$ROOT/gates/local_quality_gate.sh" prepush-lite',
        "pre-push standard prepush-lite lane",
    )
    _assert_contains(
        pre_push_gate,
        'step fast-lane bash "$ROOT/gates/local_quality_gate.sh" fast',
        "pre-push strict fast lane",
    )
    assert "check_upstream_verification_freshness.py" not in local_quality_gate
    assert "check_upstream_receipts.py" not in local_quality_gate
    assert "check_gate_log_correlation.py" not in local_quality_gate


def test_local_fast_skips_unrelated_python_and_frontend_work() -> None:
    local_quality_gate = (_repo_root() / "tooling" / "gates" / "local_quality_gate.sh").read_text(encoding="utf-8")

    _assert_contains(local_quality_gate, 'echo "__NONE__"', "local fast no-python-change sentinel")
    _assert_contains(
        local_quality_gate,
        "No changed Python files detected; skip mypy.",
        "local fast skip mypy on non-python changes",
    )
    _assert_contains(
        local_quality_gate,
        "No changed Python files detected; skip pytest.",
        "local fast skip pytest on non-python changes",
    )
    _assert_contains(local_quality_gate, "detect_changed_frontend_files()", "local fast frontend change detector")
    _assert_contains(
        local_quality_gate,
        "lint-frontend skipped (no frontend changes detected)",
        "local fast skip frontend lint on unrelated changes",
    )


def test_pre_commit_ai_context_and_ci_change_detection_are_config_driven() -> None:
    repo_root = _repo_root()
    pre_commit = (repo_root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    ai_context_script = (repo_root / "tooling" / "scripts" / "check_ai_context_files.py").read_text(encoding="utf-8")
    change_detection_script = (repo_root / "tooling" / "scripts" / "check_change_detection_scope.py").read_text(encoding="utf-8")
    change_detection_helper = (repo_root / "tooling" / "ci" / "detect_change_scope.sh").read_text(encoding="utf-8")
    pre_push_gate = (repo_root / "tooling" / "gates" / "pre_push_gate.sh").read_text(encoding="utf-8")

    _assert_contains(pre_commit, "check_ai_context_files.py", "pre-commit ai context script")
    _assert_contains(ai_context_script, "ai_context_registry.json", "ai context registry reference")
    _assert_contains(ci, "bash tooling/ci/detect_change_scope.sh", "ci change detection helper entry")
    _assert_contains(change_detection_script, "change_detection_scope.json", "ci change detection scope config")
    _assert_contains(change_detection_helper, "check_change_detection_scope.py", "change detection helper delegates to scope script")
    assert 'step fast-lane env FILEYARD_ALLOW_HOST_EXECUTION=1 bash "$ROOT/scripts/local_quality_gate.sh" fast' not in pre_push_gate


def test_lock_drift_contract_uses_dev_lock_and_shell_forwarder() -> None:
    repo_root = _repo_root()
    quality_gate = (repo_root / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")
    local_quality_gate = (repo_root / "tooling" / "gates" / "local_quality_gate.sh").read_text(encoding="utf-8")
    lock_drift = (repo_root / "tooling" / "scripts" / "check_lock_drift.py").read_text(encoding="utf-8")
    dev_shell = (repo_root / "tooling" / "requirements-dev.txt").read_text(encoding="utf-8")

    _assert_contains(quality_gate, "check_lock_drift.py", "quality gate lock drift check")
    _assert_contains(local_quality_gate, "check_lock_drift.py", "local gate lock drift check")
    _assert_contains(
        lock_drift,
        'dev_lock = root / "tooling" / "requirements-dev.lock.txt"',
        "lock drift script checks dev lock file",
    )
    _assert_contains(
        lock_drift,
        '_assert_shell_target(dev_shell, "-r requirements-dev.lock.txt", errors)',
        "lock drift script enforces dev shell target",
    )
    _assert_contains(dev_shell, "-r requirements-dev.lock.txt", "dev shell lock forward contract")


def test_prepush_gate_defaults_to_standard_mode() -> None:
    """Pre-push gate defaults to standard mode for faster local feedback.

    Standard mode: prepush-lite + commit governance (<30s)
    Strict mode: fast lane + mutation canary (<90s)
    Full mode: strict + full quality gate (5-15min)
    """
    pre_push_gate = (_repo_root() / "tooling" / "gates" / "pre_push_gate.sh").read_text(encoding="utf-8")
    _assert_contains(pre_push_gate, 'MODE="${1:-${FILEYARD_PRE_PUSH_MODE:-standard}}"', "pre-push default mode standard")


def test_ci_change_detection_expands_heavy_scope_and_catches_deletions() -> None:
    ci = (_repo_root() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    helper = (_repo_root() / "tooling" / "ci" / "detect_change_scope.sh").read_text(encoding="utf-8")
    assert helper.count("--diff-filter=ACDMRT") >= 2, "change-detection helper must include deleted files for PR/push paths"
    _assert_contains(ci, "bash tooling/ci/detect_change_scope.sh .github/.ci_changed_files.txt", "shared change-detection helper call")
    _assert_contains(helper, "check_change_detection_scope.py", "change-detection helper shared scope script")
    scope_data = json.loads((_repo_root() / "contracts" / "governance" / "change_detection_scope.json").read_text(encoding="utf-8"))
    heavy_globs = set(scope_data["heavy_globs"])
    assert "AGENTS.md" in heavy_globs, "change-detection high-risk governance file AGENTS.md"
    assert "CLAUDE.md" in heavy_globs, "change-detection high-risk governance file CLAUDE.md"
    assert ".env.example" in heavy_globs, "change-detection high-risk env template"
    assert "apps/cli/fileyard.py" in heavy_globs, "change-detection core CLI entrypoint"
    assert "contracts/runtime/config.example.toml" in heavy_globs, "change-detection config template"
    assert "contracts/runtime/manifest.schema.json" in heavy_globs, "change-detection manifest schema"
    assert "tooling/requirements*.txt" in heavy_globs, "change-detection dependency lock/dev requirements"
    assert "apps/webui/**/*" in heavy_globs, "change-detection must treat any webui change as heavy"
    assert "package.json" in heavy_globs, "change-detection root package.json"
    assert "package-lock.json" in heavy_globs, "change-detection root package-lock.json"
    assert "tooling/config/biome.json" in heavy_globs, "change-detection frontend lint/build config"
    assert "tooling/config/frontend-scope.yml" in heavy_globs, "change-detection frontend scope contract"


def test_ci_test_job_enforces_strict_pytest_markers_and_config() -> None:
    ci = (_repo_root() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    _assert_contains(ci, "--strict-config --strict-markers", "ci unit strict pytest flags")
    _assert_contains(ci, "--strict-config", "ci e2e strict pytest config")
    _assert_contains(ci, "--strict-markers", "ci e2e strict pytest markers")


def test_local_ci_matrix_gate_enforces_strict_pytest_markers_and_config() -> None:
    matrix_gate = (_repo_root() / "tooling" / "gates" / "local_ci_matrix_gate.sh").read_text(encoding="utf-8")
    _assert_contains(matrix_gate, "--strict-config", "local matrix strict pytest config")
    _assert_contains(matrix_gate, "--strict-markers", "local matrix strict pytest markers")
    _assert_contains(matrix_gate, "docker build \\", "local matrix builds local CI image family")
    _assert_contains(matrix_gate, '--file "$DOCKERFILE_PATH"', "local matrix uses devcontainer dockerfile")
    _assert_contains(matrix_gate, "--require-hashes -r requirements-dev.lock.txt", "local matrix installs dev lock")
    _assert_contains(
        matrix_gate,
        "directly from /opt/fileyard-ci-venv",
        "local matrix uses the image-baked runtime venv directly",
    )
    _assert_contains(
        matrix_gate,
        'export FILEYARD_VENV_DIR="/opt/fileyard-ci-venv"',
        "local matrix documents matrix runtime venv dir contract",
    )
    _assert_contains(matrix_gate, "image-baked, hash-locked", "local matrix consumes image-baked runtime")
    _assert_contains(matrix_gate, "requirements-dev.lock.txt is missing a setuptools pin", "local matrix enforces setuptools bootstrap pin")
    assert "python:${py_ver}-slim" not in matrix_gate
    assert "fallback to local python runtimes" not in matrix_gate
    assert "using local python runtimes" not in matrix_gate


def test_live_integration_requires_secrets_and_uses_image_contract() -> None:
    live_ci = (_repo_root() / ".github" / "workflows" / "live-integration.yml").read_text(encoding="utf-8")
    _assert_contains(live_ci, "name: live-image-contract", "live integration image contract artifact")
    _assert_contains(live_ci, "runs-on: ubuntu-latest", "live integration hosted runner routing")
    _assert_contains(live_ci, "timeout-minutes: 35", "live integration timeout window")
    _assert_contains(live_ci, "Load CI runtime image from contract", "live integration image contract load step")
    _assert_contains(
        live_ci,
        "GHCR_PULL_TOKEN: ${{ secrets.GHCR_PUSH_TOKEN || github.token }}",
        "live integration ghcr pull token fallback wiring",
    )
    _assert_contains(
        live_ci,
        "GHCR_PULL_USERNAME: ${{ vars.GHCR_PUSH_USERNAME || github.actor }}",
        "live integration ghcr pull username fallback wiring",
    )
    _assert_contains(live_ci, 'LIVE_MAX_DURATION_SECONDS: "1800"', "live integration hosted max duration budget")
    _assert_contains(live_ci, "GEMINI_MODEL: ${{ secrets.GEMINI_MODEL }}", "live integration gemini model secret wiring")
    _assert_contains(live_ci, "missing required secret GEMINI_API_KEY", "live integration gemini key preflight")
    _assert_contains(live_ci, "missing required secret GEMINI_MODEL", "live integration gemini model preflight")
    _assert_contains(live_ci, "missing required secret FILEYARD_LIVE_TEST_URL", "live integration url preflight")


def test_env_contract_deprecated_vars_are_fully_removed() -> None:
    repo_root = _repo_root()
    quality_gate = (repo_root / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")
    run_live = (repo_root / "tooling" / "runtime" / "run_live_tests.sh").read_text(encoding="utf-8")
    env_contract_vars = _extract_contract_vars_from_registry()
    env_contract_doc = (repo_root / "docs" / "env_contract.md").read_text(encoding="utf-8")
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")
    deprecated_vars = (
        "GEMINI_MODEL_PRIMARY",
        "GEMINI_MODEL_FALLBACK",
        "CONFIDENCE_THRESHOLD",
    )

    for name in deprecated_vars:
        assert name not in quality_gate, f"quality_gate should ignore deprecated env var: {name}"
        assert name not in run_live, f"run_live_tests should ignore deprecated env var: {name}"
        assert name not in env_contract_vars, f"check_env_contract should remove deprecated env var: {name}"
        assert name not in env_contract_doc, f"env_contract.md should remove deprecated env var: {name}"
        assert name not in env_example, f".env.example should remove deprecated env var: {name}"


def test_env_contract_budget_is_explicit_in_all_gates() -> None:
    """Env contract budget check is in quality gates and CI, not pre-commit.

    Pre-commit is kept lightweight; env contract check is in local_quality_gate and CI.
    """
    # Keep this assertion aligned with the current env contract expansion budget.
    repo_root = _repo_root()
    quality_gate = (repo_root / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")
    local_quality_gate = (repo_root / "tooling" / "gates" / "local_quality_gate.sh").read_text(encoding="utf-8")
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    _assert_contains(quality_gate, "--max-contract-size 59", "quality_gate env contract budget")
    _assert_contains(local_quality_gate, "--max-contract-size 59", "local_quality_gate env contract budget")
    _assert_contains(ci, "--max-contract-size 59", "ci env contract budget")


def test_env_example_points_to_workspace_runtime_env() -> None:
    repo_root = _repo_root()
    env_contract_doc = (repo_root / "docs" / "env_contract.md").read_text(encoding="utf-8")
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")

    _assert_contains(env_contract_doc, "<workspace-root>/.fileyard/env/runtime.env", "env contract workspace runtime env path")
    _assert_contains(env_example, "<workspace-root>/.fileyard/env/runtime.env", "env example workspace runtime env path")
    _assert_contains(env_example, "repository root .env file is local-only convenience", "env example repo-root .env warning")
    assert "Copy to .env and fill real values." not in env_example


def test_env_contract_report_is_wired_into_quality_and_ci() -> None:
    repo_root = _repo_root()
    quality_gate = (repo_root / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")
    local_quality_gate = (repo_root / "tooling" / "gates" / "local_quality_gate.sh").read_text(encoding="utf-8")
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    baseline = repo_root / "contracts" / "governance" / "baselines" / "env_contract_baseline.json"
    report_script = repo_root / "tooling" / "scripts" / "generate_env_contract_report.py"
    baseline_update_script = repo_root / "tooling" / "scripts" / "update_env_contract_baseline.py"

    _assert_contains(quality_gate, "generate_env_contract_report.py", "quality_gate env report command")
    _assert_contains(local_quality_gate, "generate_env_contract_report.py", "local_quality_gate env report command")
    _assert_contains(ci, "ci-env-contract-report", "CI env report gate label")
    _assert_contains(ci, "generate_env_contract_report.py", "CI env report command")
    assert baseline.exists(), "env contract baseline file must exist"
    assert report_script.exists(), "env contract report script must exist"
    assert baseline_update_script.exists(), "env contract baseline update script must exist"

    baseline_payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert baseline_payload.get("contract_total") == 29, "contract baseline must be frozen at 29"
    assert baseline_payload.get("broad_total") == 44, "broad baseline must be frozen at 44"
    assert baseline_payload.get("observed_business_envs") == 23, "observed baseline must be frozen at 23"
    assert baseline_payload.get("baseline_update_policy") == "governance-cycle-only"

    report_script_text = report_script.read_text(encoding="utf-8")
    _assert_contains(report_script_text, "contract_total", "env report includes contract_total")
    _assert_contains(report_script_text, "broad_total", "env report includes broad_total")
    _assert_contains(
        report_script_text,
        "observed_business_envs",
        "env report includes observed_business_envs",
    )
    _assert_contains(
        report_script_text,
        "contract_total_delta_vs_baseline",
        "env report includes contract_total delta",
    )
    _assert_contains(report_script_text, "contract_total_trend", "env report includes contract_total trend")
    _assert_contains(
        report_script_text,
        "broad_total_delta_vs_baseline",
        "env report includes broad_total delta",
    )
    _assert_contains(report_script_text, "broad_total_trend", "env report includes broad_total trend")
    _assert_contains(
        report_script_text,
        "observed_business_envs_delta_vs_baseline",
        "env report includes observed_business_envs delta",
    )
    _assert_contains(
        report_script_text,
        "observed_business_envs_trend",
        "env report includes observed_business_envs trend",
    )
    _assert_contains(
        report_script_text,
        "summary=",
        "env report outputs one-line summary",
    )
    _assert_contains(
        report_script_text,
        "budget_summary=",
        "env report outputs budget summary",
    )
    _assert_contains(report_script_text, "--governance-ticket", "env report governance ticket flag")
    _assert_contains(
        report_script_text,
        "report broad-total override blocked",
        "env report blocks broad override outside governance cycle",
    )

    baseline_update_script_text = baseline_update_script.read_text(encoding="utf-8")
    _assert_contains(baseline_update_script_text, "--governance-ticket", "baseline update governance ticket flag")
    _assert_contains(
        baseline_update_script_text,
        "observed_business_envs",
        "baseline update includes observed_business_envs",
    )

    env_contract_doc = (repo_root / "docs" / "env_contract.md").read_text(encoding="utf-8")
    _assert_contains(env_contract_doc, "Do not modify the baseline outside a governance cycle", "doc baseline freeze statement")
    _assert_contains(
        env_contract_doc,
        "--broad-total",
        "doc explains governance-only broad-total override policy",
    )
    _assert_contains(env_contract_doc, "env_contract_registry.yaml", "doc points to registry SSOT")
    generated_ref = repo_root / "docs" / "reference" / "env_contract.generated.md"
    assert generated_ref.exists(), "generated env reference must exist"
    runtime_ref = repo_root / "docs" / "reference" / "runtime_topology.generated.md"
    assert runtime_ref.exists(), "generated runtime topology reference must exist"


def test_env_contract_doc_and_gate_script_stay_in_sync() -> None:
    repo_root = _repo_root()
    env_doc = (repo_root / "docs" / "reference" / "env_contract.generated.md").read_text(encoding="utf-8")

    gate_vars = _extract_contract_vars_from_registry()
    doc_vars = _extract_contract_vars_from_doc(env_doc)

    missing_in_doc = sorted(gate_vars - doc_vars)
    missing_in_gate = sorted(doc_vars - gate_vars)

    assert not missing_in_doc, f"env_contract.md missing vars from gate script: {missing_in_doc}"
    assert not missing_in_gate, f"check_env_contract.py missing vars from env_contract.md: {missing_in_gate}"


def test_env_contract_live_coverage_vars_and_budgets_are_consistent() -> None:
    contract = _extract_contract_vars_from_registry()
    budgets = _extract_category_budgets_from_registry()

    assert "LIVE_COVERAGE_FILE" in contract
    assert "FILEYARD_LIVE_COVERAGE_FILE" in contract
    assert len(contract) <= 59

    live_count = sum(1 for name in contract if name.startswith("LIVE_"))
    movi_count = sum(1 for name in contract if name.startswith("FILEYARD_"))
    assert live_count <= budgets["LIVE_"]
    assert movi_count <= budgets["FILEYARD_"]


def test_run_web_stack_uses_compose_project_name_fallback() -> None:
    run_web_stack = (_repo_root() / "tooling" / "runtime" / "run_web_stack.sh").read_text(encoding="utf-8")

    _assert_contains(
        run_web_stack,
        'COMPOSE_PROJECT_NAME_FALLBACK="${COMPOSE_PROJECT_NAME:-}"',
        "run_web_stack compose project fallback seed",
    )
    _assert_contains(run_web_stack, 'load_governance_defaults "$REPO_ROOT"', "run_web_stack governance bootstrap")
    _assert_contains(
        run_web_stack,
        'COMPOSE_PROJECT_NAME_FALLBACK="$GOVERNANCE_COMPOSE_PROJECT_NAME_DEFAULT"',
        "run_web_stack compose project fallback default",
    )
    _assert_contains(
        run_web_stack,
        'env COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME_FALLBACK" docker compose',
        "run_web_stack compose project fallback execution",
    )


def test_run_web_api_hashes_lockfiles_from_repo_root() -> None:
    run_web_api = (_repo_root() / "tooling" / "runtime" / "run_web_api.sh").read_text(encoding="utf-8")

    _assert_contains(
        run_web_api,
        'cat "$REPO_ROOT/tooling/requirements.lock.txt" "$REPO_ROOT/tooling/requirements-dev.lock.txt"',
        "run_web_api lockfile hash inputs stay anchored at repo root",
    )
    assert 'cat "$ROOT/tooling/requirements.lock.txt"' not in run_web_api


def test_run_webui_reinstalls_when_lock_hash_changes() -> None:
    run_webui = (_repo_root() / "tooling" / "runtime" / "run_webui.sh").read_text(encoding="utf-8")
    defaults = _load_governance_defaults()

    _assert_contains(
        run_webui,
        'if [ -f "$REPO_ROOT/apps/webui/package-lock.json" ]; then',
        "run_webui package-lock branch",
    )
    _assert_contains(
        run_webui,
        'npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" ci',
        "run_webui deterministic install",
    )
    _assert_contains(
        run_webui,
        'WEBUI_HASH_FILE="$(governance_webui_lock_hash_path "$REPO_ROOT")"',
        "run_webui lock hash file",
    )
    assert defaults["GOVERNANCE_WEBUI_INSTALL_MODE"] == "lockfile-ci"
    _assert_contains(
        run_webui,
        'cat "$REPO_ROOT/apps/webui/package.json" "$REPO_ROOT/apps/webui/package-lock.json"',
        "run_webui lock hash input",
    )
    _assert_contains(
        run_webui,
        'npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$REPO_ROOT/apps/webui" ls --depth=0',
        "run_webui dependency tree health check",
    )
    _assert_contains(run_webui, '[ "$webui_deps_hash" != "$prev_webui_deps_hash" ]', "run_webui stale dependency detection")
    _assert_contains(run_webui, 'printf "%s" "$webui_deps_hash" > "$WEBUI_HASH_FILE"', "run_webui lock hash persistence")


def test_devcontainer_pins_node24_for_web_stack() -> None:
    dockerfile = (_repo_root() / ".devcontainer" / "Dockerfile").read_text(encoding="utf-8")
    defaults = _load_governance_defaults()

    _assert_contains(dockerfile, defaults["GOVERNANCE_NODE_RUNTIME_IMAGE"], "devcontainer node runtime version")


def test_container_exec_sets_workspace_safe_directory_for_ci_container_runs() -> None:
    container_exec = (_repo_root() / "tooling" / "scripts" / "container_exec.sh").read_text(encoding="utf-8")

    _assert_contains(
        container_exec,
        "git config --global --add safe.directory /workspace",
        "container_exec git safe.directory bootstrap",
    )


def test_ci_uses_pre_checkout_hygiene_for_early_shared_pool_jobs() -> None:
    ci = (_repo_root() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for job_name in (
        "build-ci-image",
        "atomic-commit-gate-hosted-primary",
        "atomic-commit-gate-hosted-retry",
        "secrets-supply-chain-gate-hosted-retry",
        "ci-hardening-gate-hosted-primary",
        "ci-hardening-gate-hosted-retry",
    ):
        _assert_contains(ci, job_name, f"{job_name} exists")
    _assert_contains(
        ci,
        "bash tooling/ci/gha_self_hosted_hygiene.sh --stage pre-checkout --normalize-ownership",
        "ci pre-checkout hygiene hook",
    )
    _assert_contains(ci, "Hosted cleanup jobs do not run repo-local hygiene before checkout.", "hosted cleanup pre-checkout no-op")


def test_required_checks_policy_declares_failure_domain_contract() -> None:
    policy = (_repo_root() / "contracts" / "governance" / "required_checks_policy.yaml").read_text(encoding="utf-8")

    for job_name in (
        "fork-pr-safety-gate",
        "commit-message-lint",
        "atomic-commit-gate",
        "secrets-supply-chain-gate",
        "ci-hardening-gate",
        "webui-build-test",
        "packaging-gate",
        "quality-gate-full",
        "functional-gate",
        "test",
        "mutation-canary-gate",
    ):
        _assert_contains(policy, f"job_id: {job_name}", f"{job_name} required check policy entry")
    assert policy.count("failure_domain_policy:") >= 13
    assert policy.count("failure_domain_reason:") >= 13
    _assert_contains(policy, "hosted-primary-plus-hosted-retry", "dual failure-domain policy option")
    assert "shared-pool-only-accepted" not in policy
    assert "hosted-primary-plus-shared-pool-fallback" not in policy


def test_readme_ci_governance_facts_use_generated_blocks() -> None:
    repo_root = _repo_root()
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    script_readme = (repo_root / "docs" / "usage.md").read_text(encoding="utf-8")
    manual_fact_rules = (repo_root / "contracts" / "docs" / "docs_manual_fact_rules.yaml").read_text(encoding="utf-8")

    _assert_contains(readme, "<!-- BEGIN GENERATED: root-ci-governance-summary -->", "root readme generated CI block")
    _assert_contains(script_readme, "<!-- BEGIN GENERATED: script-readme-ci-governance-summary -->", "script readme generated CI block")
    _assert_contains(manual_fact_rules, "manual-ci-governance:", "manual CI governance rule")
    _assert_contains(manual_fact_rules, "CI 真值路径 vs 开发 fallback 路径：", "manual CI heading ban")
    _assert_contains(manual_fact_rules, "failure-domain 说明：", "manual failure-domain ban")


def test_ci_workflow_uses_hosted_primary_plus_fallback_for_required_gates() -> None:
    ci = (_repo_root() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for job_name in (
        "lint-backend-hosted-primary",
        "lint-backend-hosted-retry",
        "lint-backend",
        "lint-frontend-hosted-primary",
        "lint-frontend-hosted-retry",
        "lint-frontend",
        "webui-build-test-hosted-primary",
        "webui-build-test-hosted-retry",
        "webui-build-test",
        "quality-gate-full-hosted-primary",
        "quality-gate-full-hosted-retry",
        "quality-gate-full",
        "packaging-gate-hosted-primary",
        "packaging-gate-hosted-retry",
        "packaging-gate",
        "mutation-canary-gate-hosted-primary",
        "mutation-canary-gate-hosted-retry",
        "mutation-canary-gate",
        "live-smoke-preflight-hosted-primary",
        "live-smoke-preflight-hosted-retry",
        "live-smoke-preflight",
        "functional-gate-hosted-primary",
        "functional-gate-hosted-retry",
        "functional-gate",
        "test-hosted-primary",
        "test-hosted-retry",
        "test",
    ):
        _assert_contains(ci, job_name, f"{job_name} exists")

    for gate_name in (
        "lint-backend",
        "lint-frontend",
        "webui-build-test",
        "quality-gate-full",
        "packaging-gate",
        "mutation-canary-gate",
        "live-smoke-preflight",
        "functional-gate",
        "test",
    ):
        helper_call = f"resolve_dual_lane_gate.sh {gate_name}"
        hosted_success = f"✅ {gate_name} passed on hosted primary lane."
        fallback_success = f"✅ {gate_name} retry passed on hosted retry lane."
        assert helper_call in ci or hosted_success in ci, f"{gate_name} resolver hosted success missing"
        assert helper_call in ci or fallback_success in ci, f"{gate_name} resolver fallback success missing"
    _assert_contains(ci, "runs-on: ubuntu-latest", "hosted primary lanes run on ubuntu-latest")
    _assert_contains(ci, "environment: owner-approved-sensitive", "protected environment for sensitive jobs")


def test_local_ci_script_keeps_ci_hardening_step() -> None:
    ci_local = _load_ci_local_body()

    _assert_contains(ci_local, "check_ci_workflow_hardening.py --workflow .github/workflows/ci.yml", "ci:local hardening step")
    _assert_contains(ci_local, "check_repo_runtime_residue.py --root .", "ci:local repo runtime residue gate")
    _assert_contains(ci_local, "check_upstream_verification_freshness.py --root .", "ci:local upstream freshness gate")
    _assert_contains(
        ci_local,
        "bash tooling/upstreams/refresh_receipts.sh --bundle .runtime-cache/logs/evidence-bundle.local.json",
        "ci:local governed receipt refresh",
    )


def test_local_ci_script_emits_local_metrics_and_evidence_bundle() -> None:
    ci_local = _load_ci_local_body()

    _assert_contains(
        ci_local,
        "collect_ci_run_metrics.py --output .runtime-cache/logs/ci-run-metrics.local.json",
        "ci:local local metrics output",
    )
    _assert_contains(
        ci_local,
        "generate_ci_evidence_bundle.py --artifacts-root .runtime-cache --output .runtime-cache/logs/evidence-bundle.local.json",
        "ci:local local evidence bundle output",
    )


def test_local_ci_script_uses_governed_python_entrypoint() -> None:
    ci_local = _load_ci_local_body()

    _assert_contains(ci_local, '. "$CONFIG_LIB"', "ci:local sources governance config lib")
    _assert_contains(ci_local, 'apply_runtime_env_defaults "$REPO_ROOT"', "ci:local applies runtime env defaults")
    _assert_contains(
        ci_local,
        'governance_python "$REPO_ROOT" tooling/scripts/generate_ci_evidence_bundle.py',
        "ci:local uses governed python for evidence bundle",
    )


def test_local_ci_script_fail_fast_marks_runner_capability_as_environment_boundary() -> None:
    ci_local = _load_ci_local_body()

    _assert_contains(ci_local, "if ! bash tooling/scripts/check_runner_capabilities.sh; then", "ci:local runner capability fail-fast")
    _assert_contains(
        ci_local,
        "environment blocked before repo-side checks",
        "ci:local environment-boundary wording",
    )


def test_run_webui_task_host_cleanup_is_best_effort() -> None:
    script = (_repo_root() / "tooling" / "runtime" / "run_webui_task.sh").read_text(encoding="utf-8")

    _assert_contains(script, "cleanup_host_webui_mountpoint()", "host-side node_modules cleanup helper")
    _assert_contains(script, "should not masquerade as a repo-side", "best-effort cleanup rationale")
    _assert_contains(script, 'rm -rf "$REPO_ROOT/apps/webui/node_modules"/* 2>/dev/null || true', "best-effort inner cleanup")
    _assert_contains(script, 'rmdir "$REPO_ROOT/apps/webui/node_modules" 2>/dev/null || true', "best-effort empty-dir cleanup")
    _assert_contains(script, "clear_dir_contents()", "shared node_modules clear helper")


def test_quality_gate_runs_runtime_cleanliness_after_short_checks_settle() -> None:
    quality_gate = (_repo_root() / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")

    short_wait_idx = quality_gate.find('wait "$short_pid"')
    runtime_layout_idx = quality_gate.find('("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_layout.py"')
    runtime_residue_idx = quality_gate.find('("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_repo_runtime_residue.py"')
    runtime_budget_idx = quality_gate.find('("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_runtime_budget.py"')
    feature_state_idx = quality_gate.find('("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_feature_state_layout.py"')
    strategy_pack_idx = quality_gate.find('("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_strategy_pack_registry.py"')
    watch_sources_idx = quality_gate.find('("$VENV/bin/python" "$REPO_ROOT/tooling/scripts/check_watch_sources_contract.py"')

    assert short_wait_idx != -1, "quality_gate must wait for short-checks before runtime cleanliness checks"
    assert runtime_layout_idx != -1, "quality_gate runtime-layout step missing"
    assert runtime_residue_idx != -1, "quality_gate repo-runtime-residue step missing"
    assert runtime_budget_idx != -1, "quality_gate runtime-budget step missing"
    assert feature_state_idx != -1, "quality_gate feature-state-layout step missing"
    assert strategy_pack_idx != -1, "quality_gate strategy-pack-registry step missing"
    assert watch_sources_idx != -1, "quality_gate watch-sources-contract step missing"
    assert short_wait_idx < runtime_layout_idx < runtime_residue_idx < runtime_budget_idx
    _assert_contains(
        quality_gate,
        "runtime cleanliness checks out of the parallel preflight fan-out",
        "quality_gate runtime cleanliness ordering rationale",
    )


def test_local_ci_refreshes_receipts_before_final_verify() -> None:
    ci_local = _load_ci_local_body()

    refresh_idx = ci_local.find("bash tooling/upstreams/refresh_receipts.sh --bundle .runtime-cache/logs/evidence-bundle.local.json")
    verify_idx = ci_local.find("bash tooling/gates/verify_repo_final.sh")
    docs_smoke_idx = ci_local.find("bash tooling/docs/docs_smoke.sh --install-smoke")
    prune_idx = ci_local.find("bash tooling/cleanup/prune_repo_runtime.sh", docs_smoke_idx)

    assert refresh_idx != -1, "ci:local must refresh receipts before final verify"
    assert verify_idx != -1, "ci:local must still run final verify"
    assert prune_idx != -1, "ci:local must prune runtime residue again before final verify"
    assert prune_idx < refresh_idx < verify_idx
    assert refresh_idx < verify_idx
