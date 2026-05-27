from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_quality_gate_cleans_stale_coverage_snapshots_before_running() -> None:
    quality_gate = (_repo_root() / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")

    assert "cleanup_coverage_artifacts()" in quality_gate
    assert '-name "coverage-*.xml"' in quality_gate
    assert '! -name "coverage-debug-*.xml"' in quality_gate
    assert 'rm -f "$RUNTIME_CI_DIR/coverage.xml"' in quality_gate
    assert 'rm -f "$REPO_ROOT/.runtime-cache/test/coverage/coverage.xml"' in quality_gate
    assert "find \"$REPO_ROOT/.runtime-cache/test/coverage\" -maxdepth 1 -type f -name '.coverage*' -delete" in quality_gate
    assert "cleanup_coverage_artifacts\nrun_step_with_heartbeat \\\n  pytest-fast \\" in quality_gate


def test_quality_gate_writes_coverage_xml_only_from_full_non_live_suite() -> None:
    quality_gate = (_repo_root() / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")

    fast_step = "run_step_with_heartbeat \\\n  pytest-fast \\"
    mutation_step = "run_step mutation-canary"
    full_step = (
        "run_step_with_heartbeat \\\n"
        "  pytest \\\n"
        "  run_pytest_with_isolated_tmp \\\n"
        "  env -u PRE_COMMIT_FROM_REF -u PRE_COMMIT_TO_REF FILEYARD_RUN_LIVE_TESTS=0"
    )
    threshold_step = 'run_step coverage-threshold "$VENV/bin/python" "$ROOT/scripts/check_coverage_thresholds.py"'

    fast_start = quality_gate.find(fast_step)
    mutation_start = quality_gate.find(mutation_step)
    full_start = quality_gate.find(full_step)
    threshold_start = quality_gate.find(threshold_step)

    assert fast_start != -1, "pytest-fast step missing"
    assert mutation_start != -1, "mutation-canary step missing"
    assert full_start != -1, "full pytest step missing"
    assert threshold_start != -1, "coverage threshold step missing"

    fast_block = quality_gate[fast_start:mutation_start]
    full_block = quality_gate[full_start:threshold_start]

    assert "--cov=" not in fast_block
    assert "--cov-report=xml:" not in fast_block

    assert "--cov=packages/domain" in full_block
    assert "--cov=packages/application" in full_block
    assert "--cov=packages/infrastructure" in full_block
    assert "--cov-branch" in full_block
    assert '--cov-report=xml:"$RUNTIME_CI_DIR/coverage.xml"' in full_block
    assert "pytest_full_targets=(" in quality_gate
    assert "tests/unit" in quality_gate
    assert "tests/e2e" in quality_gate
    assert "tests/integration" in quality_gate
    assert '"${pytest_full_targets[@]}"' in full_block


def test_quality_gate_normalizes_fallback_coverage_xml_before_threshold() -> None:
    quality_gate = (_repo_root() / "tooling" / "gates" / "quality_gate.sh").read_text(encoding="utf-8")

    assert "normalize_coverage_artifact()" in quality_gate
    assert 'cp "$fallback_coverage_xml" "$RUNTIME_CI_DIR/coverage.xml"' in quality_gate
    assert '"$VENV/bin/python" -m coverage combine "$fallback_coverage_dir"' in quality_gate
    assert '"$VENV/bin/python" -m coverage xml -o "$RUNTIME_CI_DIR/coverage.xml"' in quality_gate
    assert "normalize_coverage_artifact || {" in quality_gate
