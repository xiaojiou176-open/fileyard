from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def _script_root() -> Path:
    return Path(__file__).resolve().parents[2] / "tooling"


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _git(cwd: Path, *args: str) -> str:
    proc = _run(["git", *args], cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _init_git_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@example.com")
    _git(repo, "config", "user.name", "CI Bot")


def _prepare_doc_drift_repo(repo: Path) -> Path:
    scripts_dir = repo / "tooling" / "scripts"
    docs_contract_dir = repo / "contracts" / "docs"
    generated_dir = repo / "docs" / "_generated"
    contracts_api_dir = repo / "contracts" / "api"
    scripts_dir.mkdir(parents=True)
    docs_contract_dir.mkdir(parents=True)
    generated_dir.mkdir(parents=True)
    contracts_api_dir.mkdir(parents=True)

    source_script = _script_root() / "scripts" / "check_doc_drift.py"
    target_script = scripts_dir / "check_doc_drift.py"
    target_script.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
    source_render = _script_root() / "scripts" / "render_docs.py"
    target_render = scripts_dir / "render_docs.py"
    target_render.write_text(source_render.read_text(encoding="utf-8"), encoding="utf-8")
    source_lib = _script_root() / "scripts" / "docs_render_lib.py"
    target_lib = scripts_dir / "docs_render_lib.py"
    target_lib.write_text(source_lib.read_text(encoding="utf-8"), encoding="utf-8")

    (docs_contract_dir / "docs_render_manifest.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "render_state_path: docs/_generated/render_state.json",
                "renders:",
                "  - id: docs-fragment",
                "    kind: fragment",
                "    renderer: readme-web-api-summary",
                "    source_paths:",
                "      - pyproject.toml",
                "    output_path: README.md",
                "    block_id: fixture-block",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (repo / "pyproject.toml").write_text("[project]\nname = 'doc-drift-fixture'\n", encoding="utf-8")
    (contracts_api_dir / "web_api.openapi.yaml").write_text(
        "openapi: 3.1.0\ninfo:\n  title: fixture\n  version: '1'\npaths: {}\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "# baseline\n\n<!-- BEGIN GENERATED: fixture-block -->\nplaceholder\n<!-- END GENERATED: fixture-block -->\n",
        encoding="utf-8",
    )
    (generated_dir / "render_state.json").write_text("{}\n", encoding="utf-8")

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore: init doc drift fixtures")
    return target_script


def _prepare_docs_scope_repo(repo: Path) -> Path:
    scripts_dir = repo / "tooling" / "scripts"
    docs_contract_dir = repo / "contracts" / "docs"
    docs_dir = repo / "docs"
    (docs_dir / "reference").mkdir(parents=True)
    (docs_dir / "_generated").mkdir(parents=True)
    (docs_dir / "_archive").mkdir(parents=True)
    scripts_dir.mkdir(parents=True)
    docs_contract_dir.mkdir(parents=True)

    for name in ("check_docs_scope.py", "docs_render_lib.py"):
        source = _script_root() / "scripts" / name
        target = scripts_dir / name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    (docs_contract_dir / "docs_nav_registry.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "docs:",
                "  - path: docs/AGENTS.md",
                "    layer: human-authored",
                "    scope: strict",
                "  - path: docs/CLAUDE.md",
                "    layer: human-authored",
                "    scope: strict",
                "  - path: docs/reference/example.generated.md",
                "    layer: render-only",
                "    scope: generated",
                "  - path: docs/_generated/render_state.json",
                "    layer: render-only",
                "    scope: generated",
                "  - path: docs/_archive/history.md",
                "    layer: archive",
                "    scope: soft",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (docs_dir / "AGENTS.md").write_text("# docs agents\n", encoding="utf-8")
    (docs_dir / "CLAUDE.md").write_text("# docs claude\n", encoding="utf-8")
    (docs_dir / "reference" / "example.generated.md").write_text("# generated\n", encoding="utf-8")
    (docs_dir / "_generated" / "render_state.json").write_text("{}\n", encoding="utf-8")
    (docs_dir / "_archive" / "history.md").write_text("# history\n", encoding="utf-8")
    return scripts_dir / "check_docs_scope.py"


def _prepare_docs_fragment_completeness_repo(repo: Path) -> Path:
    scripts_dir = repo / "tooling" / "scripts"
    docs_contract_dir = repo / "contracts" / "docs"
    docs_dir = repo / "docs"
    scripts_dir.mkdir(parents=True)
    docs_contract_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)

    for name in ("check_docs_fragment_completeness.py", "docs_render_lib.py"):
        source = _script_root() / "scripts" / name
        target = scripts_dir / name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    (docs_contract_dir / "docs_render_manifest.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "render_state_path: docs/_generated/render_state.json",
                "renders:",
                "  - id: root-runtime-topology",
                "    kind: fragment",
                "    renderer: root-runtime-topology-summary",
                "    source_paths:",
                "      - pyproject.toml",
                "    output_path: README.md",
                "    block_id: root-runtime-topology",
                "  - id: open-source-platform-truth",
                "    kind: fragment",
                "    renderer: open-source-platform-truth-summary",
                "    source_paths:",
                "      - pyproject.toml",
                "    output_path: docs/open_source_runbook.md",
                "    block_id: open-source-platform-truth",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (docs_contract_dir / "docs_nav_registry.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "docs:",
                "  - path: README.md",
                "    layer: fragment-rendered",
                "    scope: strict",
                "    generated_blocks:",
                "      - root-runtime-topology",
                "  - path: docs/open_source_runbook.md",
                "    layer: human-authored",
                "    scope: strict",
                "    generated_blocks:",
                "      - open-source-platform-truth",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text("[project]\nname = 'fragment-fixture'\n", encoding="utf-8")
    (repo / "README.md").write_text("# readme\n", encoding="utf-8")
    (docs_dir / "open_source_runbook.md").write_text("# runbook\n", encoding="utf-8")
    return scripts_dir / "check_docs_fragment_completeness.py"


def _prepare_manual_facts_repo(repo: Path) -> Path:
    scripts_dir = repo / "tooling" / "scripts"
    docs_contract_dir = repo / "contracts" / "docs"
    scripts_dir.mkdir(parents=True)
    docs_contract_dir.mkdir(parents=True)
    for name in ("check_docs_manual_facts.py", "docs_render_lib.py"):
        source = _script_root() / "scripts" / name
        target = scripts_dir / name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (docs_contract_dir / "docs_manual_fact_rules.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "target_layers:",
                "  - fragment-rendered",
                "rules:",
                "  manual-api-inventory:",
                "    patterns:",
                '      - "任务接口族："',
                "  manual-runtime-topology:",
                "    patterns:",
                '      - "Compose 服务名："',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (docs_contract_dir / "docs_nav_registry.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "docs:",
                "  - path: README.md",
                "    layer: fragment-rendered",
                "    scope: strict",
                "  - path: docs/usage.md",
                "    layer: fragment-rendered",
                "    scope: strict",
                "    manual_fact_rule_exemptions:",
                "      - manual-runtime-topology",
                "  - path: docs/architecture.md",
                "    layer: fragment-rendered",
                "    scope: strict",
                "  - path: apps/webui/README.md",
                "    layer: fragment-rendered",
                "    scope: strict",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# ok\n", encoding="utf-8")
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "usage.md").write_text("# ok\n", encoding="utf-8")
    (repo / "docs" / "architecture.md").write_text("# ok\n", encoding="utf-8")
    (repo / "apps" / "webui").mkdir(parents=True, exist_ok=True)
    (repo / "apps" / "webui" / "README.md").write_text("# ok\n", encoding="utf-8")
    return scripts_dir / "check_docs_manual_facts.py"


def test_upgrade_deps_invokes_piptools_module_instead_of_wrapper_binary() -> None:
    script = (_script_root() / "upstreams" / "upgrade_deps.sh").read_text(encoding="utf-8")

    assert '"$LOCK_VENV_DIR/bin/python" -m piptools compile \\' in script
    assert '"$LOCK_VENV_DIR/bin/pip-compile"' not in script
    assert "to_repo_relative_path()" in script
    assert 'cd "$REPO_ROOT"' in script


def _prepare_ai_context_repo(repo: Path) -> Path:
    scripts_dir = repo / "tooling" / "scripts"
    config_dir = repo / "contracts" / "governance"
    scripts_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    source = _script_root() / "scripts" / "check_ai_context_files.py"
    target = scripts_dir / "check_ai_context_files.py"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "ai_context_registry.json").write_text(
        '{"required_any":["CLAUDE.md","AGENTS.md"],"required_all":["docs/AGENTS.md"]}\n',
        encoding="utf-8",
    )
    return target


def _prepare_change_detection_repo(repo: Path) -> Path:
    scripts_dir = repo / "tooling" / "scripts"
    config_dir = repo / "contracts" / "governance"
    scripts_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    source = _script_root() / "scripts" / "check_change_detection_scope.py"
    target = scripts_dir / "check_change_detection_scope.py"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "change_detection_scope.json").write_text(
        '{"heavy_globs":["packages/application/*","packages/application/**/*","packages/domain/*","packages/domain/**/*","packages/infrastructure/*","packages/infrastructure/**/*","README.md","apps/webui/*","apps/webui/**/*"]}\n',
        encoding="utf-8",
    )
    return target


def _prepare_ssot_hash_repo(repo: Path) -> Path:
    scripts_dir = repo / "tooling" / "scripts"
    docs_contract_dir = repo / "contracts" / "docs"
    runtime_contract_dir = repo / "contracts" / "runtime"
    generated_dir = repo / "docs" / "_generated"
    reference_dir = repo / "docs" / "reference"
    scripts_dir.mkdir(parents=True)
    docs_contract_dir.mkdir(parents=True)
    runtime_contract_dir.mkdir(parents=True)
    generated_dir.mkdir(parents=True)
    reference_dir.mkdir(parents=True)
    for name in ("check_docs_ssot_hash.py", "docs_render_lib.py"):
        source = _script_root() / "scripts" / name
        target = scripts_dir / name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (docs_contract_dir / "docs_render_manifest.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "render_state_path: docs/_generated/render_state.json",
                "renders:",
                "  - id: reference",
                "    kind: file",
                "    renderer: env-contract-reference",
                "    source_paths:",
                "      - contracts/runtime/env_contract_registry.yaml",
                "    output_path: docs/reference/env_contract.generated.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (runtime_contract_dir / "env_contract_registry.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "business_env_prefixes: [MOVI_]",
                "ignored_suffixes: []",
                "category_budgets: {MOVI_: 1}",
                "forbidden_env_example_keys: []",
                "deprecated_removal_deadlines: {}",
                "sections:",
                "  required: [MOVI_ONE]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output = reference_dir / "env_contract.generated.md"
    output.write_text("# generated\n", encoding="utf-8")
    state = generated_dir / "render_state.json"
    state.write_text(
        '{"renders":[{"output_path":"docs/reference/env_contract.generated.md","source_hashes":{"contracts/runtime/env_contract_registry.yaml":"bad"},"output_hash":"bad"}]}\n',
        encoding="utf-8",
    )
    return scripts_dir / "check_docs_ssot_hash.py"


def _make_executable_script(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _valid_ci_workflow_text() -> str:
    return (_script_root().parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_docs_smoke_entrypoint_check_passes_for_fast_help(tmp_path: Path) -> None:
    entrypoint = _make_executable_script(
        tmp_path / "quick-entry",
        '#!/usr/bin/env bash\nif [ "${1:-}" = "--help" ]; then\n  echo \'usage: quick-entry\'\n  exit 0\nfi\nexit 1\n',
    )
    checker = _script_root() / "scripts" / "docs_smoke_entrypoint_check.py"

    proc = _run(
        [
            sys.executable,
            str(checker),
            "--entrypoint-path",
            str(entrypoint),
            "--entrypoint-name",
            "quick-entry",
            "--timeout-seconds",
            "1",
        ],
        cwd=tmp_path,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out


def test_docs_smoke_entrypoint_check_fails_for_timeout(tmp_path: Path) -> None:
    entrypoint = _make_executable_script(
        tmp_path / "slow-entry",
        "#!/usr/bin/env bash\nsleep 3\n",
    )
    checker = _script_root() / "scripts" / "docs_smoke_entrypoint_check.py"

    proc = _run(
        [
            sys.executable,
            str(checker),
            "--entrypoint-path",
            str(entrypoint),
            "--entrypoint-name",
            "slow-entry",
            "--timeout-seconds",
            "1",
        ],
        cwd=tmp_path,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "slow-entry" in out
    assert "timed out after 1s" in out


def test_docs_smoke_install_smoke_uses_entrypoint_wrapper() -> None:
    script = (_script_root() / "docs" / "docs_smoke.sh").read_text(encoding="utf-8")
    assert "docs_smoke_entrypoint_check.py" in script
    assert "--timeout-seconds" in script


def test_docs_smoke_install_smoke_uses_machine_temp_root() -> None:
    script = (_script_root() / "docs" / "docs_smoke.sh").read_text(encoding="utf-8")
    assert 'install_root="${DOCS_SMOKE_INSTALL_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/movi-organizer/docs-smoke-install}"' in script
    assert '".runtime-cache/tmp/docs-smoke.' not in script
    assert 'TMPDIR="$install_runtime_tmp" TMP="$install_runtime_tmp" TEMP="$install_runtime_tmp"' in script


def test_atomic_commit_gate_staged_blocks_large_staged_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    (repo / "a.txt").write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
    _git(repo, "add", "a.txt")

    script = _script_root() / "scripts" / "check_atomic_commits.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--mode",
            "staged",
            "--max-files",
            "1",
            "--max-lines",
            "3",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "failed (staged)" in out


def test_no_logs_gate_auto_uses_pre_push_refs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    src = repo / "src"
    src.mkdir(parents=True)
    _init_git_repo(repo)

    (src / "base.py").write_text("print('ok')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat(base): initial")
    base_sha = _git(repo, "rev-parse", "HEAD")

    (src / "bad.sh").write_text("echo 'something went wrong'\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fix(log): add low quality log")

    (src / "clean.py").write_text("print('still clean')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore(clean): add clean file")
    head_sha = _git(repo, "rev-parse", "HEAD")

    script = _script_root() / "scripts" / "check_no_logs_no_merge.py"
    env = os.environ.copy()
    env["PRE_COMMIT_FROM_REF"] = base_sha
    env["PRE_COMMIT_TO_REF"] = head_sha

    proc = _run(
        [
            sys.executable,
            str(script),
            "--root",
            str(repo),
            "--mode",
            "auto",
            "--scan-path",
            "src",
        ],
        cwd=repo,
        env=env,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "LOW_QUALITY_LOG_PHRASE" in out
    assert "bad.sh" in out


def test_commit_message_gate_checks_only_to_ref_side_commits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)

    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat(base): init")
    main_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")

    _git(repo, "checkout", "-b", "feature/test-range")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fix(feature): valid message")
    feature_head = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", main_branch)
    (repo / "main-only.txt").write_text("main-only\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "invalid message without conventional prefix")
    main_head = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "feature/test-range")
    script = _script_root() / "scripts" / "check_commit_message.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--from-ref",
            main_head,
            "--to-ref",
            feature_head,
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "passed" in out


def test_commit_message_gate_empty_range_can_fail_in_strict_mode(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)

    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat(base): init")
    head_sha = _git(repo, "rev-parse", "HEAD")

    script = _script_root() / "scripts" / "check_commit_message.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--from-ref",
            head_sha,
            "--to-ref",
            head_sha,
            "--require-non-empty-range",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "no commits found in range" in out
    assert "strict mode" in out


def test_atomic_commit_gate_checks_only_to_ref_side_commits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)

    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat(base): init")
    main_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")

    _git(repo, "checkout", "-b", "feature/atomic-range")
    (repo / "small.txt").write_text("a\nb\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fix(atomic): small change")
    feature_head = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", main_branch)
    (repo / "huge.txt").write_text("\n".join(f"line-{i}" for i in range(120)), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore(main): large unrelated commit")
    main_head = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "feature/atomic-range")
    script = _script_root() / "scripts" / "check_atomic_commits.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--from-ref",
            main_head,
            "--to-ref",
            feature_head,
            "--max-files",
            "2",
            "--max-lines",
            "10",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "passed" in out


def test_atomic_commit_gate_merge_base_range_ignores_main_history_after_branch_sync(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)

    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat(base): init")
    main_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")

    _git(repo, "checkout", "-b", "feature/atomic-merge-base")
    (repo / "small.txt").write_text("a\nb\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fix(atomic): small change")

    _git(repo, "checkout", main_branch)
    for idx in range(120):
        (repo / f"huge-{idx}.txt").write_text(f"line-{idx}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore(main): large unrelated commit")

    _git(repo, "checkout", "feature/atomic-merge-base")
    _git(repo, "merge", "--no-ff", main_branch, "-m", "chore(sync): merge main into feature")
    synced_head = _git(repo, "rev-parse", "HEAD")
    merge_base = _git(repo, "merge-base", main_branch, synced_head)

    script = _script_root() / "scripts" / "check_atomic_commits.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--from-ref",
            merge_base,
            "--to-ref",
            synced_head,
            "--max-files",
            "2",
            "--max-lines",
            "10",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "passed" in out


def test_atomic_commit_gate_empty_range_can_fail_in_strict_mode(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)

    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat(base): init")
    head_sha = _git(repo, "rev-parse", "HEAD")

    script = _script_root() / "scripts" / "check_atomic_commits.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--from-ref",
            head_sha,
            "--to-ref",
            head_sha,
            "--require-non-empty-range",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "no commits found in range" in out
    assert "strict mode" in out


def test_ci_workflow_schedule_allows_empty_commit_ranges_for_commit_and_atomic_gates() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    empty_range_guard = 'if [ "${{ github.event_name }}" = "workflow_dispatch" ] || [ "${{ github.event_name }}" = "schedule" ]; then'
    assert workflow.count(empty_range_guard) >= 4
    assert "workflow_dispatch/schedule: allow empty commit range for hosted primary gate" in workflow
    assert "workflow_dispatch/schedule: allow empty commit range for fallback gate" in workflow


def test_ci_atomic_commit_gate_uses_pull_request_head_range_for_same_repo_branches() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert workflow.count('TO_REF="HEAD"') >= 2
    assert workflow.count("CI_HEAD_REF: ${{ github.event.pull_request.head.ref }}") >= 2
    assert workflow.count('HEAD_REF="origin/${CI_HEAD_REF}"') >= 2
    assert workflow.count('git fetch --no-tags --prune --depth=200 origin "${CI_HEAD_REF}"') >= 2
    assert workflow.count('BASE_REF="$(git merge-base "$BASE_BRANCH" "$HEAD_REF" 2>/dev/null || true)"') >= 2
    assert workflow.count('TO_REF="$HEAD_REF"') >= 2
    assert workflow.count('if [ "${{ github.event.pull_request.head.repo.full_name }}" = "${{ github.repository }}" ]; then') >= 2


def test_ci_commit_message_gate_uses_pull_request_head_range_for_same_repo_branches() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert workflow.count("CI_HEAD_REF: ${{ github.event.pull_request.head.ref }}") >= 4
    assert workflow.count('HEAD_REF="origin/${CI_HEAD_REF}"') >= 4
    assert workflow.count('git fetch --no-tags --prune --depth=200 origin "${{ github.base_ref }}"') >= 2
    assert workflow.count('git fetch --no-tags --prune --depth=200 origin "${CI_HEAD_REF}"') >= 4
    assert workflow.count('BASE_REF="$(git merge-base "$BASE_BRANCH" "$HEAD_REF" 2>/dev/null || true)"') >= 4
    assert (
        workflow.count('python3 tooling/scripts/check_commit_message.py --from-ref "$BASE_REF" --to-ref "$TO_REF" "${RANGE_FLAGS[@]}"') >= 2
    )
    assert workflow.count('if [ "${{ github.event.pull_request.head.repo.full_name }}" = "${{ github.repository }}" ]; then') >= 4


def test_runtime_bootstrap_recreates_venv_without_removing_mount_root() -> None:
    root = Path(__file__).resolve().parents[2]
    bootstrap = (root / "tooling" / "runtime" / "bootstrap_env.sh").read_text(encoding="utf-8")
    container_exec = (root / "tooling" / "scripts" / "container_exec.sh").read_text(encoding="utf-8")

    for script in (bootstrap, container_exec):
        assert 'rm -rf "$target"' not in script
        assert 'find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf {} +' in script


def test_ci_workflow_bootstraps_dev_deps_for_fastapi_jobs() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "Build and publish CI runtime image family" in workflow
    assert workflow.count("name: ci-image-contract") >= 5
    assert workflow.count("Download CI runtime image contract") >= 5
    assert workflow.count("Load CI runtime image from contract") >= 5
    assert "docker login ghcr.io" in workflow
    assert 'IMAGE_BASE="ghcr.io/${{ github.repository_owner }}/movi-ci"' in workflow
    assert 'echo "DOCKER_CONFIG=$DOCKER_CONFIG_DIR" >> "$GITHUB_ENV"' in workflow
    assert 'IMAGE_REF="$(bash tooling/ci/read_ci_contract_image_ref.sh .runtime-cache/ci-contract/py311.image.txt)"' in workflow
    assert "MATRIX_PYTHON_VERSION: ${{ matrix.python-version }}" in workflow
    assert 'IMAGE_REF="$(bash tooling/ci/read_ci_contract_image_ref.sh ".runtime-cache/ci-contract/${image_file}")"' in workflow
    assert 'docker pull "$IMAGE_REF"' in workflow
    assert 'echo "MOVI_CI_IMAGE=$IMAGE_REF" >> "$GITHUB_ENV"' in workflow
    assert "bash tooling/scripts/container_exec.sh --label functional-gate --" in workflow
    assert "bash tooling/scripts/container_exec.sh --label test-gates --" in workflow
    assert "bash tooling/scripts/container_exec.sh --label mutation-canary --" in workflow
    assert "py311-venv-quality-gate-" not in workflow
    assert ".venv/bin/python -m pip install -r requirements-dev.txt" not in workflow
    assert 'echo "❌ build-ci-image: missing required secret GHCR_PUSH_TOKEN" >&2' in workflow
    assert 'printf \'%s\' "$GHCR_PUSH_TOKEN" | docker login ghcr.io -u "$GHCR_PUSH_USERNAME" --password-stdin' in workflow
    assert "GHCR push failed with GHCR_PUSH_TOKEN, retrying with github.token" not in workflow


def test_reusable_runtime_builder_requires_secret_only_push_credentials() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "reusable-build-runtime-image.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert 'echo "❌ reusable-build-runtime-image: missing required secret GHCR_PUSH_TOKEN" >&2' in workflow
    assert 'echo "DOCKER_CONFIG=$DOCKER_CONFIG_DIR" >> "$GITHUB_ENV"' in workflow
    assert 'printf \'%s\' "$GHCR_PUSH_TOKEN" | docker login ghcr.io -u "$GHCR_PUSH_USERNAME" --password-stdin' in workflow
    assert "GHCR push failed with GHCR_PUSH_TOKEN, retrying with github.token" not in workflow


def test_ci_cleanup_resources_stays_shell_only() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    cleanup_block = workflow.split("  cleanup-resources:\n", 1)[1]
    cleanup_block = cleanup_block.split("\n# full-heavy-trigger", 1)[0]

    assert "Four-Rail Runtime Cleanup" in cleanup_block
    assert "actions/setup-python" not in cleanup_block
    assert "Restore Python cache" not in cleanup_block
    assert "Install dependencies (if needed)" not in cleanup_block
    assert "Hosted cleanup jobs do not run repo-local hygiene before checkout." in cleanup_block


def test_atomic_commit_gate_pre_push_auto_handles_multiline_from_ref_env(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)

    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat(base): init")
    base_sha = _git(repo, "rev-parse", "HEAD")

    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fix(gate): small change")
    head_sha = _git(repo, "rev-parse", "HEAD")

    script = _script_root() / "scripts" / "check_atomic_commits.py"
    env = os.environ.copy()
    env["PRE_COMMIT_FROM_REF"] = f"{base_sha}\n{head_sha}"
    env["PRE_COMMIT_TO_REF"] = head_sha
    proc = _run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--pre-push-auto",
            "--max-files",
            "3",
            "--max-lines",
            "20",
        ],
        cwd=repo,
        env=env,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "passed" in out


def test_atomic_commit_gate_pre_push_auto_falls_back_to_origin_main_when_branch_has_no_upstream(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)

    _git(repo, "branch", "-M", "main")
    for idx in range(45):
        (repo / f"seed-{idx}.txt").write_text(f"{idx}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat(seed): large baseline")
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _git(repo, "checkout", "-b", "feature/no-upstream")
    (repo / "delta.txt").write_text("delta\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fix(gate): scoped change")

    script = _script_root() / "scripts" / "check_atomic_commits.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--pre-push-auto",
            "--max-files",
            "10",
            "--max-lines",
            "40",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "passed" in out


def test_commit_message_gate_pre_push_auto_falls_back_to_origin_main_when_branch_has_no_upstream(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)

    _git(repo, "branch", "-M", "main")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "bootstrap baseline")
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    _git(repo, "checkout", "-b", "feature/no-upstream")
    (repo / "delta.txt").write_text("delta\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fix(gate): scoped change")

    script = _script_root() / "scripts" / "check_commit_message.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--pre-push-auto",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "passed" in out


def test_env_contract_gate_blocks_unregistered_business_env(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    code_dir = repo / "packages" / "application"
    code_dir.mkdir(parents=True)
    _init_git_repo(repo)
    (code_dir / "sample.py").write_text(
        "import os\n\ndef run() -> str:\n    return os.getenv('MOVI_NEW_PHASE_E_FLAG', '')\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_env_contract.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--root",
            str(repo),
            "--mode",
            "all",
            "--scan-path",
            "packages/application",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "not registered in env_contract" in out
    assert "MOVI_NEW_PHASE_E_FLAG" in out


def test_env_contract_gate_passes_for_registered_business_env(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    code_dir = repo / "packages" / "application"
    code_dir.mkdir(parents=True)
    _init_git_repo(repo)
    (code_dir / "sample.py").write_text(
        "import os\n\ndef run() -> str:\n    return os.getenv('MOVI_TRACE_ID', '')\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_env_contract.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--root",
            str(repo),
            "--mode",
            "all",
            "--scan-path",
            "packages/application",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "env_contract: passed" in out


def test_env_contract_gate_blocks_missing_env_example_contract_keys(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    (repo / ".env.example").write_text("GEMINI_API_KEY=\n", encoding="utf-8")

    script = _script_root() / "scripts" / "check_env_contract.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--root",
            str(repo),
            "--mode",
            "all",
            "--scan-path",
            "packages/application",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert ".env.example is missing contract keys" in out
    assert "GEMINI_MODEL" in out


def test_env_contract_gate_blocks_forbidden_legacy_env_example_keys(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    (repo / ".env.example").write_text(
        "GEMINI_API_KEY=\nGEMINI_MODEL=\nGEMINI_MODEL_PRIMARY=\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_env_contract.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--root",
            str(repo),
            "--mode",
            "all",
            "--scan-path",
            "packages/application",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert ".env.example contains forbidden legacy/example keys" in out
    assert "GEMINI_MODEL_PRIMARY" in out


def test_env_contract_gate_blocks_non_contract_env_example_keys(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    (repo / ".env.example").write_text(
        "GEMINI_API_KEY=\nGEMINI_MODEL=\nUNTRACKED_RUNTIME_KEY=\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_env_contract.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--root",
            str(repo),
            "--mode",
            "all",
            "--scan-path",
            "packages/application",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert ".env.example contains non-contract keys" in out
    assert "UNTRACKED_RUNTIME_KEY" in out


def test_env_contract_gate_blocks_oversized_contract(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    (repo / ".env.example").write_text("GEMINI_API_KEY=\nGEMINI_MODEL=\n", encoding="utf-8")

    script = _script_root() / "scripts" / "check_env_contract.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--root",
            str(repo),
            "--mode",
            "all",
            "--scan-path",
            "packages/application",
            "--max-contract-size",
            "1",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "contract size exceeded" in out


def test_env_contract_gate_rejects_invalid_today_arg(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)

    script = _script_root() / "scripts" / "check_env_contract.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--root",
            str(repo),
            "--mode",
            "all",
            "--scan-path",
            "packages/application",
            "--max-contract-size",
            "100",
            "--today",
            "2099-13-40",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 2
    assert "invalid --today date" in out


def test_env_contract_gate_blocks_category_budget_overflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)

    script = _script_root() / "scripts" / "check_env_contract.py"
    proc = _run(
        [
            sys.executable,
            str(script),
            "--root",
            str(repo),
            "--mode",
            "all",
            "--scan-path",
            "packages/application",
            "--max-contract-size",
            "100",
            "--today",
            "2026-01-01",
            "--category-budget",
            "MOVI_=1",
        ],
        cwd=repo,
    )

    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "category budget exceeded" in out
    assert "MOVI_" in out


def test_doc_drift_auto_mode_merges_staged_and_unstaged(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    script = _prepare_doc_drift_repo(repo)

    tracked_code = repo / "pyproject.toml"
    tracked_code.write_text("[project]\nname = 'doc-drift-fixture-updated'\n", encoding="utf-8")
    _git(repo, "add", str(tracked_code.relative_to(repo)))
    render = repo / "tooling" / "scripts" / "render_docs.py"
    render_proc = _run([sys.executable, str(render), "--root", str(repo)], cwd=repo)
    assert render_proc.returncode == 0, render_proc.stdout + render_proc.stderr

    proc = _run([sys.executable, str(script), "--mode", "auto"], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "doc-drift: ok (render sources + outputs changed)" in out
    assert "pyproject.toml" in out
    assert "README.md" in out


def test_doc_drift_auto_mode_ignores_unknown_pre_push_refs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    script = _prepare_doc_drift_repo(repo)

    tracked_code = repo / "pyproject.toml"
    tracked_code.write_text("[project]\nname = 'doc-drift-fixture-updated'\n", encoding="utf-8")
    _git(repo, "add", str(tracked_code.relative_to(repo)))
    render = repo / "tooling" / "scripts" / "render_docs.py"
    render_proc = _run([sys.executable, str(render), "--root", str(repo)], cwd=repo)
    assert render_proc.returncode == 0, render_proc.stdout + render_proc.stderr

    env = os.environ.copy()
    env["PRE_COMMIT_FROM_REF"] = "278dd64468ac1e92c6a348f2ea0684b5775fd4f2"
    env["PRE_COMMIT_TO_REF"] = "2e8e72a5e084ca9a01f1dfbacebc6e870a230b48"

    proc = _run([sys.executable, str(script), "--mode", "auto"], cwd=repo, env=env)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "doc-drift: ok (render sources + outputs changed)" in out
    assert "pyproject.toml" in out
    assert "README.md" in out


def test_doc_drift_auto_mode_merges_resolved_pre_push_range_with_local_dirty_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    script = _prepare_doc_drift_repo(repo)

    head_sha = _git(repo, "rev-parse", "HEAD")
    tracked_code = repo / "pyproject.toml"

    tracked_code.write_text("[project]\nname = 'doc-drift-fixture-local-dirty'\n", encoding="utf-8")
    _git(repo, "add", str(tracked_code.relative_to(repo)))
    render = repo / "tooling" / "scripts" / "render_docs.py"
    render_proc = _run([sys.executable, str(render), "--root", str(repo)], cwd=repo)
    assert render_proc.returncode == 0, render_proc.stdout + render_proc.stderr

    env = os.environ.copy()
    env["PRE_COMMIT_FROM_REF"] = head_sha
    env["PRE_COMMIT_TO_REF"] = head_sha

    proc = _run([sys.executable, str(script), "--mode", "auto"], cwd=repo, env=env)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "doc-drift: ok (render sources + outputs changed)" in out
    assert "pyproject.toml" in out
    assert "README.md" in out
    assert "docs/_generated/render_state.json" in out


def test_doc_drift_global_render_source_change_uses_current_render_state_not_diff_presence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    script = _prepare_doc_drift_repo(repo)

    render = repo / "tooling" / "scripts" / "render_docs.py"
    render_proc = _run([sys.executable, str(render), "--root", str(repo)], cwd=repo)
    assert render_proc.returncode == 0, render_proc.stdout + render_proc.stderr
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore: render fixtures")

    docs_render_lib = repo / "tooling" / "scripts" / "docs_render_lib.py"
    docs_render_lib.write_text(docs_render_lib.read_text(encoding="utf-8") + "\n# local comment\n", encoding="utf-8")

    proc = _run([sys.executable, str(script), "--mode", "auto"], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "doc-drift: ok" in out


def test_render_docs_produces_self_consistent_render_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    _prepare_doc_drift_repo(repo)

    render = repo / "tooling" / "scripts" / "render_docs.py"
    check_render_state = _script_root() / "scripts" / "check_docs_render_state.py"

    render_proc = _run([sys.executable, str(render), "--root", str(repo)], cwd=repo)
    assert render_proc.returncode == 0, render_proc.stdout + render_proc.stderr

    check_proc = _run([sys.executable, str(check_render_state), "--root", str(repo)], cwd=repo)
    assert check_proc.returncode == 0, check_proc.stdout + check_proc.stderr


def test_doc_drift_item_source_change_requires_render_state_refresh_even_when_output_text_is_unchanged(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    script = _prepare_doc_drift_repo(repo)

    render = repo / "tooling" / "scripts" / "render_docs.py"
    render_proc = _run([sys.executable, str(render), "--root", str(repo)], cwd=repo)
    assert render_proc.returncode == 0, render_proc.stdout + render_proc.stderr
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore: render fixtures")

    tracked_code = repo / "pyproject.toml"
    tracked_code.write_text("[project]\nname = 'doc-drift-fixture-output-unchanged'\n", encoding="utf-8")
    _git(repo, "add", str(tracked_code.relative_to(repo)))

    proc = _run([sys.executable, str(script), "--mode", "auto"], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "render-state -> docs/_generated/render_state.json" in out


def test_doc_drift_auto_mode_includes_untracked_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    script = _prepare_doc_drift_repo(repo)

    tracked_code = repo / "pyproject.toml"
    tracked_code.write_text("[project]\nname = 'doc-drift-fixture-updated'\n", encoding="utf-8")
    _git(repo, "add", str(tracked_code.relative_to(repo)))

    render = repo / "tooling" / "scripts" / "render_docs.py"
    render_proc = _run([sys.executable, str(render), "--root", str(repo)], cwd=repo)
    assert render_proc.returncode == 0, render_proc.stdout + render_proc.stderr

    proc = _run([sys.executable, str(script), "--mode", "auto"], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "doc-drift: ok (render sources + outputs changed)" in out
    assert "pyproject.toml" in out
    assert "docs/_generated/render_state.json" in out


def test_doc_drift_auto_mode_handles_non_ascii_doc_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _init_git_repo(repo)
    script = _prepare_doc_drift_repo(repo)

    config_dir = repo / "contracts" / "docs"
    manifest = config_dir / "docs_render_manifest.yaml"
    manifest.write_text(
        "\n".join(
            [
                "version: 1",
                "render_state_path: docs/_generated/render_state.json",
                "renders:",
                "  - id: non-ascii-fragment",
                "    kind: fragment",
                "    renderer: readme-web-api-summary",
                "    source_paths:",
                "      - .pre-commit-config.yaml",
                "    output_path: docs/说明文档.md",
                "    block_id: fixture-block",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    tracked_code = repo / ".pre-commit-config.yaml"
    tracked_code.write_text("repos: []\n", encoding="utf-8")
    _git(repo, "add", str(tracked_code.relative_to(repo)))

    doc_path = repo / "docs" / "说明文档.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        "# 文档更新\n\n<!-- BEGIN GENERATED: fixture-block -->\nupdated\n<!-- END GENERATED: fixture-block -->\n",
        encoding="utf-8",
    )
    render = repo / "tooling" / "scripts" / "render_docs.py"
    render_proc = _run([sys.executable, str(render), "--root", str(repo)], cwd=repo)
    assert render_proc.returncode == 0, render_proc.stdout + render_proc.stderr

    proc = _run([sys.executable, str(script), "--mode", "auto"], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "doc-drift: ok (render sources + outputs changed)" in out
    assert ".pre-commit-config.yaml" in out
    assert "docs/说明文档.md" in out


def test_docs_scope_gate_passes_for_registered_archive_generated_split(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_docs_scope_repo(repo)

    proc = _run([sys.executable, str(checker), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "docs_scope: passed" in out


def test_docs_scope_gate_blocks_legacy_docs_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_docs_scope_repo(repo)
    legacy = repo / "docs" / "code_review.md"
    legacy.write_text("# legacy report\n", encoding="utf-8")

    proc = _run([sys.executable, str(checker), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "legacy docs path must be moved out of strict docs tree" in out


def test_docs_fragment_completeness_gate_passes_when_registry_declares_all_fragment_blocks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_docs_fragment_completeness_repo(repo)

    proc = _run([sys.executable, str(checker), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "docs_fragment_completeness: passed" in out


def test_docs_fragment_completeness_gate_fails_when_nav_registry_misses_fragment_block(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_docs_fragment_completeness_repo(repo)
    (repo / "contracts" / "docs" / "docs_nav_registry.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "docs:",
                "  - path: README.md",
                "    layer: fragment-rendered",
                "    scope: strict",
                "    generated_blocks:",
                "      - root-runtime-topology",
                "  - path: docs/open_source_runbook.md",
                "    layer: human-authored",
                "    scope: strict",
                "    generated_blocks: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    proc = _run([sys.executable, str(checker), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "docs_fragment_completeness: invalid fragment registry coverage" in out
    assert "open-source-platform-truth" in out


def test_docs_scope_gate_blocks_unregistered_docs_file_in_current_docs_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_docs_scope_repo(repo)
    stray = repo / "docs" / "stray.md"
    stray.write_text("# stray\n", encoding="utf-8")

    proc = _run([sys.executable, str(checker), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "unregistered docs asset under docs: docs/stray.md" in out


def test_prune_repo_runtime_removes_root_runtime_residue(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cleanup_dir = repo / "tooling" / "cleanup"
    runtime_cache_tmp = repo / ".runtime-cache" / "tmp"
    contract_dir = repo / "contracts" / "runtime"
    cleanup_dir.mkdir(parents=True)
    runtime_cache_tmp.mkdir(parents=True)
    contract_dir.mkdir(parents=True)

    source = _script_root() / "cleanup" / "prune_repo_runtime.sh"
    script = cleanup_dir / "prune_repo_runtime.sh"
    script.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    contract = Path(__file__).resolve().parents[2] / "contracts" / "runtime" / "filesystem_layout.yaml"
    (contract_dir / "filesystem_layout.yaml").write_text(contract.read_text(encoding="utf-8"), encoding="utf-8")
    scripts_dir = repo / "tooling" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    helper = Path(__file__).resolve().parents[2] / "tooling" / "scripts" / "runtime_governance_report.py"
    (scripts_dir / "runtime_governance_report.py").write_text(helper.read_text(encoding="utf-8"), encoding="utf-8")

    root_dist = repo / "dist"
    root_logs = repo / "logs"
    app_dist = repo / "apps" / "webui" / "dist"
    app_node_modules = repo / "apps" / "webui" / "node_modules"
    closure_backups = repo / ".runtime-cache" / "closure-backups"
    history_report = repo / ".runtime-cache" / "gitleaks-history.json"
    stray_runtime_file = repo / ".runtime-cache" / "release-draft-test.md"
    for path in (root_dist, root_logs, app_dist, app_node_modules, closure_backups):
        path.mkdir(parents=True, exist_ok=True)
        (path / "marker.txt").write_text("x\n", encoding="utf-8")
    history_report.write_text("[]\n", encoding="utf-8")
    stray_runtime_file.write_text("# stray\n", encoding="utf-8")

    proc = _run(["bash", str(script), str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert not root_dist.exists()
    assert not root_logs.exists()
    assert not app_dist.exists()
    assert not app_node_modules.exists()
    assert not closure_backups.exists()
    assert not history_report.exists()
    assert not stray_runtime_file.exists()


def test_prune_repo_runtime_skips_descending_into_named_residue_dirs() -> None:
    script = (_script_root() / "cleanup" / "prune_repo_runtime.sh").read_text(encoding="utf-8")

    assert "os.walk(scan_root, topdown=True)" in script
    assert "dirnames[:] = [dirname for dirname in dirnames if dirname not in names]" in script


def test_active_legacy_sweep_ignores_local_agent_transcripts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    scripts_dir = repo / "tooling" / "scripts"
    scripts_dir.mkdir(parents=True)
    source = _script_root() / "scripts" / "check_active_legacy_sweep.py"
    target = scripts_dir / "check_active_legacy_sweep.py"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "README.md").write_text("# ok\n", encoding="utf-8")
    transcript = repo / ".agents" / "Conversations" / "turn.md"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("旧路径 `脚本/docs`\n", encoding="utf-8")

    proc = _run([sys.executable, str(target), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "active_legacy_sweep: passed" in out


def test_active_legacy_sweep_tolerates_disappearing_runtime_dirs(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    docs_dir = repo / "docs"
    repo.mkdir(parents=True)
    docs_dir.mkdir()
    (repo / "README.md").write_text("# ok\n", encoding="utf-8")
    (docs_dir / "usage.md").write_text("safe\n", encoding="utf-8")

    module = _load_module(
        _script_root() / "scripts" / "check_active_legacy_sweep.py",
        "check_active_legacy_sweep_test",
    )
    root = repo.resolve()
    missing_runtime_dir = root / ".runtime-cache" / "tmp" / "pytest-of-root" / "pytest-0"

    def fake_walk(scan_root, topdown=True, onerror=None):
        assert Path(scan_root) == root
        assert topdown is True
        assert onerror is not None
        yield str(root), [".runtime-cache", "docs"], ["README.md"]
        onerror(FileNotFoundError(str(missing_runtime_dir)))
        yield str(docs_dir.resolve()), [], ["usage.md"]

    monkeypatch.setattr(module.os, "walk", fake_walk)

    rel_paths = sorted(path.relative_to(root).as_posix() for path in module._iter_candidate_files(root))
    assert rel_paths == ["README.md", "docs/usage.md"]


def test_repo_runtime_residue_tolerates_disappearing_runtime_dirs(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    contracts_dir = repo / "contracts" / "runtime"
    scripts_dir = repo / "tooling" / "scripts"
    repo.mkdir(parents=True)
    contracts_dir.mkdir(parents=True)
    scripts_dir.mkdir(parents=True)
    source = _script_root() / "scripts" / "check_repo_runtime_residue.py"
    target = scripts_dir / "check_repo_runtime_residue.py"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (contracts_dir / "filesystem_layout.yaml").write_text(
        "repo_runtime:\n  forbidden_repo_residue_globs:\n    - apps/**/node_modules\n",
        encoding="utf-8",
    )

    module = _load_module(target, "check_repo_runtime_residue_test")
    root = repo.resolve()
    original_glob = module.Path.glob

    def flaky_glob(self, pattern):  # type: ignore[no-untyped-def]
        if self == root and pattern == "apps/**/node_modules":
            raise FileNotFoundError(str(root / "apps" / "webui" / "node_modules" / "fsevents"))
        return original_glob(self, pattern)

    monkeypatch.setattr(module.Path, "glob", flaky_glob)
    monkeypatch.setattr(sys, "argv", [str(target), "--root", str(repo)])

    assert module.main() == 0


def test_history_secret_scan_gate_writes_governed_security_output() -> None:
    script = (_script_root() / "gates" / "history_secret_scan.sh").read_text(encoding="utf-8")

    assert 'OUTPUT_DIR="${REPO_ROOT}/.runtime-cache/logs/security"' in script
    assert 'OUTPUT_JSON="${OUTPUT_DIR}/gitleaks-history.json"' in script
    assert ".runtime-cache/gitleaks-history.json" in script
    assert "gitleaks git" in script


def test_docs_manual_facts_gate_blocks_handwritten_api_inventory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_manual_facts_repo(repo)
    (repo / "README.md").write_text("任务接口族：`/api/jobs`\n", encoding="utf-8")

    proc = _run([sys.executable, str(checker), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "docs_manual_facts" in out
    assert "manual-api-inventory" in out


def test_docs_manual_facts_gate_ignores_generated_blocks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_manual_facts_repo(repo)
    (repo / "README.md").write_text(
        "# ok\n\n<!-- BEGIN GENERATED: root-web-api-routes -->\n任务接口族：`/api/jobs`\n<!-- END GENERATED: root-web-api-routes -->\n",
        encoding="utf-8",
    )

    proc = _run([sys.executable, str(checker), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "docs_manual_facts: passed" in out


def test_docs_manual_facts_gate_uses_registry_exemptions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_manual_facts_repo(repo)
    (repo / "docs" / "usage.md").write_text("Compose 服务名：`movi-ci`\n", encoding="utf-8")

    proc = _run([sys.executable, str(checker), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "docs_manual_facts: passed" in out


def test_docs_manual_facts_gate_uses_rules_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_manual_facts_repo(repo)
    (repo / "contracts" / "docs" / "docs_manual_fact_rules.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "target_layers:",
                "  - fragment-rendered",
                "rules:",
                "  manual-custom-rule:",
                "    patterns:",
                '      - "自定义漂移事实："',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "apps" / "webui" / "README.md").write_text("自定义漂移事实：`x`\n", encoding="utf-8")

    proc = _run([sys.executable, str(checker), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "manual-custom-rule" in out


def test_docs_manual_facts_gate_can_enforce_human_authored_docs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_manual_facts_repo(repo)
    (repo / "contracts" / "docs" / "docs_manual_fact_rules.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "target_layers:",
                "  - fragment-rendered",
                "rules:",
                "  manual-platform-observation:",
                "    patterns:",
                '      - "当前平台观测状态（动态检查）"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "contracts" / "docs" / "docs_nav_registry.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "docs:",
                "  - path: docs/open_source_runbook.md",
                "    layer: human-authored",
                "    scope: strict",
                "    manual_fact_enforced: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "docs" / "open_source_runbook.md").write_text("当前平台观测状态（动态检查）\n", encoding="utf-8")

    proc = _run([sys.executable, str(checker), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "manual-platform-observation" in out


def test_ai_context_files_gate_consumes_registry(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_ai_context_repo(repo)
    (repo / "AGENTS.md").write_text("# root guide\n", encoding="utf-8")
    (repo / ".cursorrules").write_text("# cursor\n", encoding="utf-8")
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "AGENTS.md").write_text("# docs guide\n", encoding="utf-8")

    proc = _run([sys.executable, str(checker)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "check-ai-context-files: passed" in out


def test_change_detection_scope_uses_config_globs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_change_detection_repo(repo)
    changed = repo / "changed.txt"
    changed.write_text("packages/application/core.py\nnotes.md\n", encoding="utf-8")

    proc = _run(
        [sys.executable, str(checker), "--changed-file-list", str(changed), "--print-mode", "plain"],
        cwd=repo,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert out.strip() == "true"


def test_docs_ssot_hash_gate_detects_stale_hashes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    checker = _prepare_ssot_hash_repo(repo)

    proc = _run([sys.executable, str(checker), "--root", str(repo)], cwd=repo)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "docs_ssot_hash" in out
    assert "source hash drift" in out or "output hash drift" in out


def test_ci_workflow_hardening_gate_passes_on_minimal_valid_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    _write_minimal_valid_ci_workflow(workflow)

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "ci-hardening: passed" in out
    assert "missing required jobs: fork-pr-safety-gate" not in out
    assert "GITLEAKS_EXPECTED_SHA256" not in out


def test_ci_workflow_hardening_gate_blocks_fetch_upstream_artifact_contract_drift(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow_text = _valid_ci_workflow_text().replace(
        '--expected-sha256 "$GITLEAKS_EXPECTED_SHA256"',
        '--url "https://example.invalid/gitleaks.tar.gz" \\\n            --output "/tmp/gitleaks.tar.gz"',
    )
    workflow.write_text(workflow_text, encoding="utf-8")

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "--url/--output" in out or "--expected-sha256" in out


def test_ci_workflow_hardening_gate_blocks_missing_functional_dependency(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow_text = _valid_ci_workflow_text()
    workflow_text = workflow_text.replace(
        (
            "needs: [change-detection, commit-message-lint, atomic-commit-gate, "
            "secrets-supply-chain-gate, quality-gate-full, mutation-canary-gate, "
            "build-ci-image]"
        ),
        (
            "needs: [change-detection, commit-message-lint, atomic-commit-gate, "
            "secrets-supply-chain-gate, mutation-canary-gate, build-ci-image]"
        ),
        1,
    )
    workflow.write_text(workflow_text, encoding="utf-8")

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "functional-gate-hosted-primary.needs must include" in out


def test_ci_workflow_hardening_gate_blocks_unpinned_actions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  commit-message-lint:
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  lint-backend:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  lint-frontend:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
  evidence-bundle:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "actions/checkout@v4" in out


def test_ci_workflow_hardening_gate_blocks_actions_without_ref(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  commit-message-lint:
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  lint-backend:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  lint-frontend:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
  evidence-bundle:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "actions/checkout" in out
    assert "must pin to 40-char commit SHA" in out


def test_ci_workflow_hardening_gate_blocks_unpinned_job_level_workflow_use(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  commit-message-lint:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  lint-backend:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  lint-frontend:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
  evidence-bundle:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
  reusable-job:
    timeout-minutes: 10
    uses: owner/repo/.github/workflows/reusable.yml@main
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "job reusable-job uses 'owner/repo/.github/workflows/reusable.yml@main'" in out


def test_ci_workflow_hardening_gate_blocks_unpinned_docker_uses(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  commit-message-lint:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  lint-backend:
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - uses: docker://alpine:3.20
  lint-frontend:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
  evidence-bundle:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "docker://alpine:3.20" in out
    assert "must pin docker image to sha256 digest" in out


def test_ci_workflow_hardening_gate_blocks_semantic_ui_audit_without_secret_wiring(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow_text = _valid_ci_workflow_text()
    workflow_text = workflow_text.replace(
        "          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}\n"
        "          GEMINI_UI_AUDIT_MODEL: ${{ vars.GEMINI_UI_AUDIT_MODEL || 'gemini-3-flash-preview' }}\n"
        '          LINT_FRONTEND_SKIP_GEMINI_AUDIT: "1"\n',
        "          GEMINI_UI_AUDIT_MODEL: gemini-3-flash-preview\n",
        1,
    )
    workflow.write_text(workflow_text, encoding="utf-8")

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "must set GEMINI_API_KEY from secrets.GEMINI_API_KEY" in out


def test_ci_workflow_hardening_gate_blocks_unpinned_actions_in_pre_commit_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  commit-message-lint:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  lint-backend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  lint-frontend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - name: Frontend lint gate
        run: bash tooling/gates/lint_frontend.sh
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GEMINI_UI_AUDIT_MODEL: ${{ vars.GEMINI_UI_AUDIT_MODEL }}
  webui-build-test:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate, lint-frontend, ci-hardening-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: npm --prefix apps/webui run test && npm --prefix apps/webui run build
  ci-hardening-gate:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  evidence-bundle:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    precommit_workflow = repo / "pre-commit.yml"
    precommit_workflow.write_text(
        """
name: pre-commit
jobs:
  pre-commit-hosted-primary:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
  pre-commit-self-hosted-fallback:
    runs-on: [self-hosted, shared-pool]
  pre-commit:
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "pre-commit.yml" in out
    assert "actions/checkout@v4" in out


def test_ci_workflow_hardening_gate_blocks_unpinned_actions_in_mutation_manual_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  commit-message-lint:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  lint-backend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  lint-frontend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - name: Frontend lint gate
        run: bash tooling/gates/lint_frontend.sh
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GEMINI_UI_AUDIT_MODEL: ${{ vars.GEMINI_UI_AUDIT_MODEL }}
  webui-build-test:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate, lint-frontend, ci-hardening-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: npm --prefix apps/webui run test && npm --prefix apps/webui run build
  ci-hardening-gate:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  evidence-bundle:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    mutation_workflow = repo / "mutation-manual.yml"
    mutation_workflow.write_text(
        """
name: mutation-manual
concurrency:
  group: mutation-manual-${{ github.ref }}
  cancel-in-progress: true
permissions:
  contents: read
jobs:
  build-ci-image:
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  python-mutmut:
    runs-on: [self-hosted, shared-pool]
    steps:
      - uses: actions/setup-python@v5
  js-stryker:
    runs-on: [self-hosted, shared-pool]
  rust-cargo-mutants:
    runs-on: [self-hosted, shared-pool]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "mutation-manual.yml" in out
    assert "actions/setup-python@v5" in out


def test_ci_workflow_hardening_gate_blocks_unpinned_third_party_actions_in_mutation_manual_workflow(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  commit-message-lint:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  lint-backend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  lint-frontend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - name: Frontend lint gate
        run: bash tooling/gates/lint_frontend.sh
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GEMINI_UI_AUDIT_MODEL: ${{ vars.GEMINI_UI_AUDIT_MODEL }}
  webui-build-test:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate, lint-frontend, ci-hardening-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: npm --prefix apps/webui run test && npm --prefix apps/webui run build
  ci-hardening-gate:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  evidence-bundle:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    mutation_workflow = repo / "mutation-manual.yml"
    mutation_workflow.write_text(
        """
name: mutation-manual
jobs:
  rust-cargo-mutants:
    runs-on: [self-hosted, shared-pool]
    steps:
      - uses: taiki-e/install-action@cargo-mutants
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "mutation-manual.yml" in out
    assert "taiki-e/install-action@cargo-mutants" in out


def test_ci_workflow_hardening_gate_allows_local_actions_in_mutation_manual_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    _write_minimal_valid_ci_workflow(workflow)

    mutation_workflow = repo / "mutation-manual.yml"
    mutation_workflow.write_text(
        """
name: mutation-manual
permissions:
  contents: read
jobs:
  python-mutmut:
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh
  js-stryker:
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh
  rust-cargo-mutants:
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh
      - uses: ./.github/actions/local-rust-tool
      - uses: taiki-e/install-action@dc65498be417cee56d567a702cfefe9337cf8ea6
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "ci-hardening: passed" in out
    assert "missing required jobs: fork-pr-safety-gate" not in out
    assert "GITLEAKS_EXPECTED_SHA256" not in out


def test_ci_workflow_hardening_gate_blocks_missing_hygiene_script_in_pre_commit_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  runner-bootstrap:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  fork-pr-safety-gate:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  commit-message-lint:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - name: Verify pinned gitleaks checksum
        env:
          GITLEAKS_EXPECTED_SHA256: ${{ vars.GITLEAKS_EXPECTED_SHA256 }}
        run: echo "$GITLEAKS_EXPECTED_SHA256" >/dev/null
  lint-backend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  lint-frontend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - name: Frontend lint gate
        run: bash tooling/gates/lint_frontend.sh
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GEMINI_UI_AUDIT_MODEL: ${{ vars.GEMINI_UI_AUDIT_MODEL }}
  webui-build-test:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate, lint-frontend, ci-hardening-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: npm --prefix apps/webui run test && npm --prefix apps/webui run build
  ci-hardening-gate:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate, webui-build-test]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  evidence-bundle:
    needs: [quality-gate-full, functional-gate, webui-build-test]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    precommit_workflow = repo / "pre-commit.yml"
    precommit_workflow.write_text(
        """
name: pre-commit
concurrency:
  group: pre-commit-${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}
  cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}
permissions:
  contents: read
jobs:
  build-ci-image:
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  pre-commit-hosted-primary:
    runs-on: [self-hosted, shared-pool]
    steps:
      - name: Clear stale git metadata before checkout
        run: |
          if [ -d "$GITHUB_WORKSPACE/.git" ]; then
            rm -rf "$GITHUB_WORKSPACE/.git"
          fi
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
  pre-commit-self-hosted-fallback:
    runs-on: [self-hosted, shared-pool]
  pre-commit:
    runs-on: [self-hosted, shared-pool]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "pre-commit.yml job pre-commit-hosted-primary must invoke gha_self_hosted_hygiene.sh after checkout" in out


def test_ci_workflow_hardening_gate_blocks_workspace_local_cache_paths_in_live_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  runner-bootstrap:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  fork-pr-safety-gate:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  commit-message-lint:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - name: Verify pinned gitleaks checksum
        env:
          GITLEAKS_EXPECTED_SHA256: ${{ vars.GITLEAKS_EXPECTED_SHA256 }}
        run: echo "$GITLEAKS_EXPECTED_SHA256" >/dev/null
  lint-backend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  lint-frontend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - name: Frontend lint gate
        run: bash tooling/gates/lint_frontend.sh
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GEMINI_UI_AUDIT_MODEL: ${{ vars.GEMINI_UI_AUDIT_MODEL }}
  webui-build-test:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate, lint-frontend, ci-hardening-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: npm --prefix apps/webui run test && npm --prefix apps/webui run build
  ci-hardening-gate:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate, webui-build-test]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  evidence-bundle:
    needs: [quality-gate-full, functional-gate, webui-build-test]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    live_workflow = repo / "live-integration.yml"
    live_workflow.write_text(
        """
name: live-integration
concurrency:
  group: live-integration-${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}
  cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}
permissions:
  contents: read
jobs:
  build-ci-image:
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  live-tests:
    runs-on: [self-hosted, shared-pool]
    env:
      PRE_COMMIT_HOME: ~/.cache/pre-commit
    steps:
      - name: Clear stale git metadata before checkout
        run: |
          if [ -d "$GITHUB_WORKSPACE/.git" ]; then
            rm -rf "$GITHUB_WORKSPACE/.git"
          fi
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
      - name: Self-hosted workspace hygiene
        run: bash tooling/ci/gha_self_hosted_hygiene.sh --stage post-checkout --normalize-ownership
      - uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830
        with:
          path: .venv
          key: bad
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "PRE_COMMIT_HOME must use runner.temp-backed path" in out
    assert "actions/cache path must not target workspace temp dir '.venv'" in out


def test_ci_workflow_hardening_gate_allows_runner_temp_hygiene_in_aux_workflows(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    _write_minimal_valid_ci_workflow(workflow)

    precommit_workflow = repo / "pre-commit.yml"
    precommit_workflow.write_text(
        """
name: pre-commit
concurrency:
  group: pre-commit-${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}
  cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}
permissions:
  contents: read
jobs:
  build-ci-image:
    if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  pre-commit-hosted-primary:
    runs-on: ubuntu-latest
    env:
      PRE_COMMIT_HOME: ${{ runner.temp }}/pre-commit-cache
      XDG_CACHE_HOME: ${{ runner.temp }}/xdg-cache
      MOVI_VENV_DIR: ${{ runner.temp }}/venv
    steps:
      - name: Clear stale git metadata before checkout
        run: |
          if [ -d "$GITHUB_WORKSPACE/.git" ]; then
            rm -rf "$GITHUB_WORKSPACE/.git"
          fi
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
      - name: Self-hosted workspace hygiene
        run: bash tooling/ci/gha_self_hosted_hygiene.sh --stage post-checkout --normalize-ownership
      - uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830
        with:
          path: ${{ runner.temp }}/venv
          key: ok
      - run: bash tooling/runtime/bootstrap_env.sh
      - run: ~/.cache/movi-organizer/venv/default/bin/pre-commit run --all-files --show-diff-on-failure --color=always
  pre-commit-hosted-retry:
    runs-on: ubuntu-latest
    steps:
      - run: bash tooling/runtime/bootstrap_env.sh
      - run: ~/.cache/movi-organizer/venv/default/bin/pre-commit run --all-files --show-diff-on-failure --color=always
  pre-commit:
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    live_workflow = repo / "live-integration.yml"
    live_workflow.write_text(
        """
name: live-integration
concurrency:
  group: live-integration-${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}
  cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}
permissions:
  contents: read
jobs:
  build-ci-image:
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  live-tests:
    runs-on: ubuntu-latest
    environment: owner-approved-sensitive
    env:
      PRE_COMMIT_HOME: ${{ runner.temp }}/pre-commit-cache
      XDG_CACHE_HOME: ${{ runner.temp }}/xdg-cache
      MOVI_VENV_DIR: ${{ runner.temp }}/venv
    steps:
      - name: Clear stale git metadata before checkout
        run: |
          if [ -d "$GITHUB_WORKSPACE/.git" ]; then
            rm -rf "$GITHUB_WORKSPACE/.git"
          fi
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
      - name: Self-hosted workspace hygiene
        run: bash tooling/ci/gha_self_hosted_hygiene.sh --stage post-checkout --normalize-ownership
      - uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830
        with:
          path: ${{ runner.temp }}/venv
          key: ok
""".strip()
        + "\n",
        encoding="utf-8",
    )

    mutation_workflow = repo / "mutation-manual.yml"
    mutation_workflow.write_text(
        """
name: mutation-manual
permissions:
  contents: read
concurrency:
  group: mutation-manual-${{ github.ref }}
  cancel-in-progress: true
jobs:
  build-ci-image:
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  python-mutmut:
    runs-on: ubuntu-latest
    env:
      XDG_CACHE_HOME: ${{ runner.temp }}/xdg-cache
      MOVI_VENV_DIR: ${{ runner.temp }}/venv
    steps:
      - name: Clear stale git metadata before checkout
        run: |
          if [ -d "$GITHUB_WORKSPACE/.git" ]; then
            rm -rf "$GITHUB_WORKSPACE/.git"
          fi
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
      - name: Self-hosted workspace hygiene
        run: bash tooling/ci/gha_self_hosted_hygiene.sh --stage post-checkout --normalize-ownership
      - uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830
        with:
          path: ${{ runner.temp }}/venv
          key: ok
  js-stryker:
    runs-on: ubuntu-latest
  rust-cargo-mutants:
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "ci-hardening: passed" in out


def test_ci_workflow_hardening_gate_blocks_pull_request_target_even_with_yaml_on_bool_key(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
on:
  pull_request_target:
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  fork-pr-safety-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  commit-message-lint:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - name: Verify pinned gitleaks checksum
        env:
          GITLEAKS_EXPECTED_SHA256: ${{ vars.GITLEAKS_EXPECTED_SHA256 }}
        run: echo "$GITLEAKS_EXPECTED_SHA256" >/dev/null
  lint-backend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  lint-frontend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - name: Frontend lint gate
        run: bash tooling/gates/lint_frontend.sh
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GEMINI_UI_AUDIT_MODEL: ${{ vars.GEMINI_UI_AUDIT_MODEL }}
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  evidence-bundle:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "workflow.on must not include pull_request_target" in out


def test_ci_workflow_hardening_gate_blocks_job_level_write_permissions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  fork-pr-safety-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  commit-message-lint:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - name: Verify pinned gitleaks checksum
        env:
          GITLEAKS_EXPECTED_SHA256: ${{ vars.GITLEAKS_EXPECTED_SHA256 }}
        run: echo "$GITLEAKS_EXPECTED_SHA256" >/dev/null
  lint-backend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    permissions:
      actions: write
  lint-frontend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - name: Frontend lint gate
        run: bash tooling/gates/lint_frontend.sh
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GEMINI_UI_AUDIT_MODEL: ${{ vars.GEMINI_UI_AUDIT_MODEL }}
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  evidence-bundle:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "job lint-backend must not grant write scopes" in out
    assert "actions=write" in out


def test_ci_workflow_hardening_gate_blocks_write_permissions_in_pre_commit_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(
        """
name: ci
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  fork-pr-safety-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  commit-message-lint:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  atomic-commit-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
  secrets-supply-chain-gate:
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - name: Verify pinned gitleaks checksum
        env:
          GITLEAKS_EXPECTED_SHA256: ${{ vars.GITLEAKS_EXPECTED_SHA256 }}
        run: echo "$GITLEAKS_EXPECTED_SHA256" >/dev/null
  lint-backend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  lint-frontend:
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - name: Frontend lint gate
        run: bash tooling/gates/lint_frontend.sh
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GEMINI_UI_AUDIT_MODEL: ${{ vars.GEMINI_UI_AUDIT_MODEL }}
  quality-gate-full:
    needs: [commit-message-lint, atomic-commit-gate, secrets-supply-chain-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/quality_gate.sh
  functional-gate:
    needs: [quality-gate-full]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/gates/functional_gate.sh
  test:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: [self-hosted, shared-pool]
  evidence-bundle:
    needs: [quality-gate-full, functional-gate]
    timeout-minutes: 10
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    precommit_workflow = repo / "pre-commit.yml"
    precommit_workflow.write_text(
        """
name: pre-commit
concurrency:
  group: pre-commit-${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}
  cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}
permissions:
  contents: read
jobs:
  build-ci-image:
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  pre-commit-hosted-primary:
    runs-on: ubuntu-latest
    permissions:
      contents: write
  pre-commit-self-hosted-fallback:
    runs-on: [self-hosted, shared-pool]
  pre-commit:
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "pre-commit.yml job pre-commit-hosted-primary must not grant write scopes" in out


def test_ci_workflow_hardening_gate_blocks_dangerous_precommit_home_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(_valid_ci_workflow_text(), encoding="utf-8")

    precommit_workflow = repo / "pre-commit.yml"
    precommit_workflow.write_text(
        """
name: pre-commit
concurrency:
  group: pre-commit-${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}
  cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}
permissions:
  contents: read
jobs:
  pre-commit-hosted-primary:
    runs-on: [self-hosted, shared-pool]
    env:
      PRE_COMMIT_HOME: ~/.cache/pre-commit
    steps:
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh pre-commit-hosted-primary
  pre-commit-self-hosted-fallback:
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh pre-commit-self-hosted-fallback
  pre-commit:
    runs-on: [self-hosted, shared-pool]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "PRE_COMMIT_HOME" in out
    assert "~/.cache/pre-commit" in out


def test_ci_workflow_hardening_gate_blocks_workspace_venv_cache_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(_valid_ci_workflow_text(), encoding="utf-8")

    live_workflow = repo / "live-integration.yml"
    live_workflow.write_text(
        """
name: live-integration
permissions:
  contents: read
concurrency:
  group: live-integration-${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}
  cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}
jobs:
  build-ci-image:
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  live-tests:
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh live-integration
      - uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830
        with:
          path: .venv
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "must not target workspace temp dir" in out
    assert ".venv" in out


def test_ci_workflow_hardening_gate_requires_hygiene_script_in_live_and_mutation_workflows(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    workflow.write_text(_valid_ci_workflow_text(), encoding="utf-8")

    live_workflow = repo / "live-integration.yml"
    live_workflow.write_text(
        """
name: live-integration
concurrency:
  group: live-integration-${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}
  cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}
permissions:
  contents: read
jobs:
  build-ci-image:
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  live-tests:
    runs-on: [self-hosted, shared-pool]
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
      - run: echo "missing hygiene script"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    mutation_workflow = repo / "mutation-manual.yml"
    mutation_workflow.write_text(
        """
name: mutation-manual
permissions:
  contents: read
concurrency:
  group: mutation-manual-${{ github.ref }}
  cancel-in-progress: true
jobs:
  build-ci-image:
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  python-mutmut:
    runs-on: [self-hosted, shared-pool]
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
      - run: echo "missing hygiene script"
  js-stryker:
    runs-on: [self-hosted, shared-pool]
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
      - run: echo "missing hygiene script"
  rust-cargo-mutants:
    runs-on: [self-hosted, shared-pool]
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
      - run: echo "missing hygiene script"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "live-integration.yml job live-tests must invoke gha_self_hosted_hygiene.sh after checkout" in out
    assert "mutation-manual.yml job python-mutmut must invoke gha_self_hosted_hygiene.sh after checkout" in out


def _write_minimal_valid_ci_workflow(workflow: Path) -> None:
    workflow.write_text(_valid_ci_workflow_text(), encoding="utf-8")


def test_ci_workflow_hardening_gate_blocks_missing_hygiene_script_in_precommit_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    _write_minimal_valid_ci_workflow(workflow)

    precommit_workflow = repo / "pre-commit.yml"
    precommit_workflow.write_text(
        """
name: pre-commit
concurrency:
  group: pre-commit-${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}
  cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}
permissions:
  contents: read
jobs:
  pre-commit-hosted-primary:
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: rm -rf "$GITHUB_WORKSPACE/.git"
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
  pre-commit-self-hosted-fallback:
    runs-on: [self-hosted, shared-pool]
    steps:
      - run: rm -rf "$GITHUB_WORKSPACE/.git"
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
  pre-commit:
    runs-on: [self-hosted, shared-pool]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "pre-commit.yml job pre-commit-hosted-primary must invoke gha_self_hosted_hygiene.sh after checkout" in out


def test_ci_workflow_hardening_gate_blocks_dangerous_cache_env_and_workspace_cache_path_in_live_workflow(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    _write_minimal_valid_ci_workflow(workflow)

    live_workflow = repo / "live-integration.yml"
    live_workflow.write_text(
        """
name: live-integration
permissions:
  contents: read
jobs:
  live-tests:
    runs-on: [self-hosted, shared-pool]
    env:
      PRE_COMMIT_HOME: ~/.cache/pre-commit
      XDG_CACHE_HOME: .cache/xdg
    steps:
      - run: rm -rf "$GITHUB_WORKSPACE/.git"
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh
      - uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830
        with:
          path: |
            .venv
            .cache/pip
          key: demo
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 1
    assert "PRE_COMMIT_HOME" in out
    assert "~/.cache/pre-commit" in out
    assert "XDG_CACHE_HOME" in out
    assert ".cache/xdg" in out
    assert "actions/cache path must not target workspace temp dir '.venv'" in out
    assert "actions/cache path must not target workspace temp dir '.cache/pip'" in out


def test_ci_workflow_hardening_gate_allows_runner_temp_cache_and_hygiene_script_in_supplemental_workflows(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

    workflow = repo / "ci.yml"
    _write_minimal_valid_ci_workflow(workflow)

    precommit_workflow = repo / "pre-commit.yml"
    precommit_workflow.write_text(
        """
name: pre-commit
concurrency:
  group: pre-commit-${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}
  cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}
permissions:
  contents: read
jobs:
  build-ci-image:
    if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  pre-commit-hosted-primary:
    runs-on: ubuntu-latest
    steps:
      - run: rm -rf "$GITHUB_WORKSPACE/.git"
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh
      - run: bash tooling/runtime/bootstrap_env.sh
      - run: ~/.cache/movi-organizer/venv/default/bin/pre-commit run --all-files --show-diff-on-failure --color=always
  pre-commit-hosted-retry:
    runs-on: ubuntu-latest
    steps:
      - run: rm -rf "$GITHUB_WORKSPACE/.git"
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh
      - run: bash tooling/runtime/bootstrap_env.sh
      - run: ~/.cache/movi-organizer/venv/default/bin/pre-commit run --all-files --show-diff-on-failure --color=always
  pre-commit:
    runs-on: ubuntu-latest
""".strip()
        + "\n",
        encoding="utf-8",
    )

    live_workflow = repo / "live-integration.yml"
    live_workflow.write_text(
        """
name: live-integration
permissions:
  contents: read
jobs:
  live-tests:
    runs-on: ubuntu-latest
    environment: owner-approved-sensitive
    env:
      PRE_COMMIT_HOME: ${{ runner.temp }}/pre-commit-cache
      XDG_CACHE_HOME: $RUNNER_TEMP/xdg-cache
    steps:
      - run: rm -rf "$GITHUB_WORKSPACE/.git"
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh
      - uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830
        with:
          path: |
            ${{ runner.temp }}/movi-live-venv
            $RUNNER_TEMP/live-cache
          key: live-demo
""".strip()
        + "\n",
        encoding="utf-8",
    )

    mutation_workflow = repo / "mutation-manual.yml"
    mutation_workflow.write_text(
        """
name: mutation-manual
permissions:
  contents: read
concurrency:
  group: mutation-manual-${{ github.ref }}
  cancel-in-progress: true
jobs:
  build-ci-image:
    uses: ./.github/workflows/reusable-build-runtime-image.yml
  python-mutmut:
    runs-on: ubuntu-latest
    steps:
      - run: rm -rf "$GITHUB_WORKSPACE/.git"
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh
  js-stryker:
    runs-on: ubuntu-latest
    steps:
      - run: rm -rf "$GITHUB_WORKSPACE/.git"
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh
  rust-cargo-mutants:
    runs-on: ubuntu-latest
    steps:
      - run: rm -rf "$GITHUB_WORKSPACE/.git"
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          clean: false
      - run: bash tooling/ci/gha_self_hosted_hygiene.sh
      - uses: taiki-e/install-action@dc65498be417cee56d567a702cfefe9337cf8ea6
""".strip()
        + "\n",
        encoding="utf-8",
    )

    script = _script_root() / "scripts" / "check_ci_workflow_hardening.py"
    proc = _run([sys.executable, str(script), "--workflow", str(workflow)], cwd=repo)
    out = proc.stdout + proc.stderr

    assert proc.returncode == 0, out
    assert "ci-hardening: passed" in out
