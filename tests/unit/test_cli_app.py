import sys
from pathlib import Path

import pytest

from apps.cli import cli_app, cli_parser


def test_cli_analyze_parses_categories(monkeypatch):
    captured = {}

    def fake_cmd(args):
        captured["args"] = args

    monkeypatch.setattr(cli_app, "cmd_analyze", fake_cmd)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "analyze",
            "--manifest",
            "/tmp/manifest.jsonl",
            "--categories",
            "工作,旅行",
        ],
    )

    cli_app.main()

    args = captured["args"]
    assert isinstance(args.categories, list)
    assert "工作" in args.categories
    assert "旅行" in args.categories
    assert "其他" in args.categories


def test_cli_apply_parses_flags(monkeypatch):
    captured = {}

    def fake_cmd(args):
        captured["args"] = args

    monkeypatch.setattr(cli_app, "cmd_apply", fake_cmd)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "apply",
            "--manifest",
            "/tmp/manifest.jsonl",
            "--output",
            "/tmp/out",
            "--categories",
            "工作",
            "--input-root",
            "/tmp/input",
            "--verify-sha1",
            "--fsync-interval",
            "10",
        ],
    )

    cli_app.main()

    args = captured["args"]
    assert args.verify_sha1 is True
    assert args.input_root == "/tmp/input"
    assert args.fsync_interval == 10
    assert args.dedupe is True
    assert "其他" in args.categories


def test_cli_rollback_parses(monkeypatch):
    captured = {}

    def fake_cmd(args):
        captured["args"] = args

    monkeypatch.setattr(cli_app, "cmd_rollback", fake_cmd)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "rollback",
            "--manifest",
            "/tmp/manifest.jsonl",
            "--overwrite",
        ],
    )

    cli_app.main()

    args = captured["args"]
    assert args.overwrite is True


def test_cli_apply_rejects_crash_inject_outside_test_mode(monkeypatch):
    monkeypatch.setattr(cli_app, "_is_test_hooks_enabled", lambda: False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "apply",
            "--manifest",
            "/tmp/manifest.jsonl",
            "--output",
            "/tmp/out",
            "--input-root",
            "/tmp/input",
            "--crash-inject",
            "after_move_before_manifest_commit",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        cli_app.main()
    assert exc_info.value.code == 2


def test_cli_apply_accepts_crash_inject_in_test_mode(monkeypatch):
    captured = {}

    def fake_cmd(args):
        captured["args"] = args

    monkeypatch.setattr(cli_app, "_is_test_hooks_enabled", lambda: True)
    monkeypatch.setattr(cli_app, "cmd_apply", fake_cmd)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "apply",
            "--manifest",
            "/tmp/manifest.jsonl",
            "--output",
            "/tmp/out",
            "--input-root",
            "/tmp/input",
            "--crash-inject",
            "after_move_before_manifest_commit",
        ],
    )
    cli_app.main()
    assert captured["args"].crash_inject == "after_move_before_manifest_commit"


def test_cli_parser_build_parser_keeps_handler_boundary():
    analyze_handler = object()
    apply_handler = object()
    rollback_handler = object()
    report_handler = object()
    parser = cli_parser.build_parser(
        lambda _section, _key, default: default,
        "",
        lambda name, default="": "gemini-test-model" if name == "GEMINI_MODEL" else default,
        {
            "analyze": analyze_handler,
            "apply": apply_handler,
            "rollback": rollback_handler,
            "report": report_handler,
        },
        "/tmp/report.json",
    )

    args = parser.parse_args(["analyze", "--manifest", "/tmp/manifest.jsonl"])

    assert args.cmd == "analyze"
    assert args.model == "gemini-test-model"
    assert args.func is analyze_handler


def test_cli_parser_apply_help_uses_english_diagnostic_copy(capsys):
    parser = cli_parser.build_parser(
        lambda _section, _key, default: default,
        "",
        lambda _name, default="": default,
        {
            "analyze": object(),
            "apply": object(),
            "rollback": object(),
            "report": object(),
        },
        "/tmp/report.json",
    )

    with pytest.raises(SystemExit):
        parser.parse_args(["apply", "--help"])

    out = capsys.readouterr().out
    assert "localized organized-" in out
    assert "Seattle timestamp" in out
    assert "product values are" in out
    assert "preserved as-is" in out


def test_cli_parser_collect_lock_targets_apply_and_report(tmp_path):
    apply_args = cli_app.argparse.Namespace(
        cmd="apply",
        manifest=str(tmp_path / "manifest.jsonl"),
        out_manifest="",
        report=str(tmp_path / "report.json"),
        rollback_manifest=str(tmp_path / "rollback.jsonl"),
    )
    apply_targets = cli_parser.collect_lock_targets(apply_args, lambda value: Path(value))
    assert str(tmp_path / "manifest.jsonl") in apply_targets
    assert str(tmp_path / "report.json") in apply_targets
    assert str(tmp_path / "rollback.jsonl") in apply_targets

    report_args = cli_app.argparse.Namespace(
        cmd="report",
        manifest=str(tmp_path / "manifest.jsonl"),
        out=str(tmp_path / "summary.json"),
    )
    report_targets = cli_parser.collect_lock_targets(report_args, lambda value: Path(value))
    assert report_targets == {str(tmp_path / "manifest.jsonl"), str(tmp_path / "summary.json")}


def test_cli_rejects_deprecated_analyze_config_key(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        """
[analyze]
GEMINI_MODEL_PRIMARY = "deprecated-model"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "--config",
            str(config),
            "analyze",
            "--manifest",
            str(tmp_path / "manifest.jsonl"),
        ],
    )

    with pytest.raises(SystemExit, match="Config validation failed"):
        cli_app.main()


def test_parse_categories_default_and_tuple():
    assert cli_app._parse_categories("") == list(cli_app.DEFAULT_CATEGORIES)
    assert "工作" in cli_app._parse_categories(("工作", "旅行"))
    assert "工作" in cli_app._parse_categories(("Work", "other"))
    assert "其他" in cli_app._parse_categories(("Work", "other"))


def test_is_test_hooks_enabled_by_env(monkeypatch):
    monkeypatch.delenv("FILEYARD_ENABLE_TEST_HOOKS", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert cli_app._is_test_hooks_enabled() is False

    monkeypatch.setenv("FILEYARD_ENABLE_TEST_HOOKS", "1")
    assert cli_app._is_test_hooks_enabled() is True


def test_read_runtime_env_value_and_resolve_env(tmp_path, monkeypatch):
    workspace_root = tmp_path / "workspace"
    runtime_env = workspace_root / ".fileyard" / "env" / "runtime.env"
    runtime_env.parent.mkdir(parents=True)
    monkeypatch.setenv("FILEYARD_WORKSPACE_ROOT", str(workspace_root))
    assert cli_app._read_runtime_env_value("GEMINI_API_KEY") == ""

    runtime_env.write_text(
        "\n".join(
            [
                "# comment",
                "INVALID_LINE",
                "OTHER_KEY=ignored",
                "GEMINI_API_KEY=' from_runtime_env '",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GEMINI_API_KEY", "from_env")
    assert cli_app._read_runtime_env_value("GEMINI_API_KEY") == "from_runtime_env"
    assert cli_app._resolve_env_prefer_runtime_env("GEMINI_API_KEY", "fallback") == "from_env"

    runtime_env.write_text("OTHER_KEY=value", encoding="utf-8")
    assert cli_app._resolve_env_prefer_runtime_env("GEMINI_API_KEY", "fallback") == "from_env"

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert cli_app._resolve_env_prefer_runtime_env("GEMINI_API_KEY", "fallback") == "fallback"


def test_runtime_env_file_wrapper(monkeypatch, tmp_path):
    expected = tmp_path / "runtime.env"
    monkeypatch.setattr(cli_app, "_shared_runtime_env_file", lambda: expected)
    assert cli_app._runtime_env_file() == expected


def test_type_helper_predicates():
    assert cli_app._is_bool(True) is True
    assert cli_app._is_int(True) is False
    assert cli_app._is_int(3) is True
    assert cli_app._is_number(1.5) is True
    assert cli_app._is_str_or_str_list("a") is True
    assert cli_app._is_str_or_str_list(["a", "b"]) is True
    assert cli_app._is_str_or_str_list(["a", 1]) is False
    assert cli_app._is_str_or_str_list(123) is False


def test_default_report_out_fallback_when_script_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_app, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("FILEYARD_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    assert cli_app._default_report_out() == str(tmp_path / "workspace" / ".fileyard" / "artifacts" / "report" / "report_summary.json")


def test_validate_output_path_conflicts_rejects_duplicates(tmp_path):
    parser = cli_app.argparse.ArgumentParser("test")

    analyze_args = cli_app.argparse.Namespace(
        cmd="analyze",
        manifest=str(tmp_path / "same.jsonl"),
        csv=str(tmp_path / "same.jsonl"),
        report="",
    )
    with pytest.raises(SystemExit) as exc_analyze:
        cli_app._validate_output_path_conflicts(parser, analyze_args)
    assert exc_analyze.value.code == 2

    report_args = cli_app.argparse.Namespace(
        cmd="report",
        manifest=str(tmp_path / "same.jsonl"),
        out=str(tmp_path / "same.jsonl"),
    )
    with pytest.raises(SystemExit) as exc_report:
        cli_app._validate_output_path_conflicts(parser, report_args)
    assert exc_report.value.code == 2


def test_validate_output_path_conflicts_apply_with_optional_outputs(tmp_path):
    parser = cli_app.argparse.ArgumentParser("test")
    args = cli_app.argparse.Namespace(
        cmd="apply",
        manifest=str(tmp_path / "manifest.jsonl"),
        out_manifest=str(tmp_path / "manifest_out.jsonl"),
        report=str(tmp_path / "report.json"),
        rollback_manifest=str(tmp_path / "rollback.jsonl"),
    )
    cli_app._validate_output_path_conflicts(parser, args)
    assert Path(args.out_manifest).name == "manifest_out.jsonl"
    assert Path(args.report).name == "report.json"
    assert Path(args.rollback_manifest).name == "rollback.jsonl"


def test_require_non_empty_arg_raises_for_blank_manifest():
    parser = cli_app.argparse.ArgumentParser("test")
    args = cli_app.argparse.Namespace(manifest="  ")
    with pytest.raises(SystemExit) as exc_info:
        cli_app._require_non_empty_arg(parser, args, "analyze", "manifest")
    assert exc_info.value.code == 2


def test_cli_apply_rejects_unknown_crash_inject(monkeypatch):
    monkeypatch.setattr(cli_app, "_is_test_hooks_enabled", lambda: True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "apply",
            "--manifest",
            "/tmp/manifest.jsonl",
            "--output",
            "/tmp/out",
            "--crash-inject",
            "not_a_valid_point",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        cli_app.main()
    assert exc_info.value.code == 2


def test_cli_config_type_error_maps_to_type_invalid_code(monkeypatch):
    events = []

    def fake_log_event(logger, level, event, message, **kwargs):
        events.append((level, event, message, kwargs.get("error_code")))

    monkeypatch.setattr(cli_app, "load_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(cli_app, "setup_logger", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(cli_app, "set_log_context_defaults", lambda **_kwargs: None)
    monkeypatch.setattr(
        cli_app,
        "validate_config",
        lambda *_args, **_kwargs: (["warn"], ["Invalid config value type: analyze.max_files"]),
    )
    monkeypatch.setattr(cli_app, "log_event", fake_log_event)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "--config",
            "/tmp/fake.toml",
            "analyze",
            "--manifest",
            "/tmp/manifest.jsonl",
        ],
    )

    with pytest.raises(SystemExit, match="Config validation failed"):
        cli_app.main()

    assert any(item[1] == "config_warning" for item in events)
    assert any(item[1] == "config_error" and item[3] == cli_app.ErrorCode.CONFIG_TYPE_INVALID.value for item in events)


def test_cli_config_chinese_unknown_section_and_key_map_to_unknown_key_code(monkeypatch):
    events = []

    def fake_log_event(logger, level, event, message, **kwargs):
        events.append((event, message, kwargs.get("error_code")))

    monkeypatch.setattr(cli_app, "load_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(cli_app, "setup_logger", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(cli_app, "set_log_context_defaults", lambda **_kwargs: None)
    monkeypatch.setattr(
        cli_app,
        "validate_config",
        lambda *_args, **_kwargs: ([], ["未知配置分组: globalx", "未知配置项: analyze.old_key"]),
    )
    monkeypatch.setattr(cli_app, "log_event", fake_log_event)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "--config",
            "/tmp/fake.toml",
            "analyze",
            "--manifest",
            "/tmp/manifest.jsonl",
        ],
    )

    with pytest.raises(SystemExit, match="Config validation failed"):
        cli_app.main()

    assert any(event == "config_error" and "Unknown config section" in message for event, message, _code in events)
    assert any(event == "config_error" and "Unknown config key" in message for event, message, _code in events)
    assert all(code == cli_app.ErrorCode.CONFIG_UNKNOWN_KEY.value for event, _message, code in events if event == "config_error")


def test_cli_config_generic_error_uses_config_invalid_code(monkeypatch):
    events = []

    def fake_log_event(logger, level, event, message, **kwargs):
        events.append((level, event, message, kwargs.get("error_code")))

    monkeypatch.setattr(cli_app, "load_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(cli_app, "setup_logger", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(cli_app, "set_log_context_defaults", lambda **_kwargs: None)
    monkeypatch.setattr(
        cli_app,
        "validate_config",
        lambda *_args, **_kwargs: ([], ["某个普通错误"]),
    )
    monkeypatch.setattr(cli_app, "log_event", fake_log_event)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "--config",
            "/tmp/fake.toml",
            "analyze",
            "--manifest",
            "/tmp/manifest.jsonl",
        ],
    )
    with pytest.raises(SystemExit, match="Config validation failed"):
        cli_app.main()
    assert any(item[1] == "config_error" and item[3] == cli_app.ErrorCode.CONFIG_INVALID.value for item in events)


def test_cli_config_load_failure_emits_error_log(monkeypatch):
    events = []

    monkeypatch.setattr(cli_app, "load_config", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad config")))
    monkeypatch.setattr(cli_app, "setup_logger", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        cli_app,
        "log_event",
        lambda logger, level, event, message, **kwargs: events.append((event, message, kwargs.get("error_code"))),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "--config",
            "/tmp/fake.toml",
            "analyze",
            "--manifest",
            "/tmp/manifest.jsonl",
        ],
    )
    with pytest.raises(SystemExit, match="Failed to load config"):
        cli_app.main()
    assert any(event == "config_load_fail" for event, _message, _code in events)


def test_cli_analyze_uses_strategy_pack_defaults_from_config(monkeypatch):
    captured = {}

    class _Pack:
        model = "gemini-3.1-pro-preview"
        categories = ("旅行", "收据")
        workers = 3

    monkeypatch.setattr(cli_app, "load_config", lambda *_args, **_kwargs: {"global": {"active_strategy_pack_id": "travel"}})
    monkeypatch.setattr(cli_app, "strategy_pack_by_id", lambda *_args, **_kwargs: _Pack())
    monkeypatch.setattr(cli_app, "cmd_analyze", lambda args: captured.setdefault("args", args))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "--config",
            "/tmp/fake.toml",
            "analyze",
            "--manifest",
            "/tmp/manifest.jsonl",
        ],
    )

    cli_app.main()
    args = captured["args"]
    assert args.model == "gemini-3.1-pro-preview"
    assert args.workers == 3
    assert "旅行" in args.categories
    assert "收据" in args.categories


def test_cli_lock_failure_releases_acquired_locks(tmp_path, monkeypatch):
    captured = {"released": []}

    def fake_acquire(path):
        if "report.json.lock" in str(path):
            raise RuntimeError("boom")
        return 7

    def fake_release(path, fd):
        captured["released"].append((str(path), fd))

    monkeypatch.setattr(cli_app, "cmd_analyze", lambda _args: None)
    monkeypatch.setattr(cli_app, "acquire_file_lock", fake_acquire)
    monkeypatch.setattr(cli_app, "release_file_lock", fake_release)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "analyze",
            "--manifest",
            str(tmp_path / "manifest.jsonl"),
            "--csv",
            str(tmp_path / "csv.csv"),
            "--report",
            str(tmp_path / "report.json"),
        ],
    )

    with pytest.raises(SystemExit, match="Failed to acquire task lock"):
        cli_app.main()

    released_paths = [item[0] for item in captured["released"]]
    assert any("manifest.jsonl.lock" in path for path in released_paths)
    assert any("csv.csv.lock" in path for path in released_paths)


def test_cli_report_locks_manifest_and_out(tmp_path, monkeypatch):
    captured = {"targets": []}

    def fake_acquire(path):
        captured["targets"].append(str(path))
        return 1

    monkeypatch.setattr(cli_app, "cmd_report", lambda _args: None)
    monkeypatch.setattr(cli_app, "acquire_file_lock", fake_acquire)
    monkeypatch.setattr(cli_app, "release_file_lock", lambda _path, _fd: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "report",
            "--manifest",
            str(tmp_path / "manifest.jsonl"),
            "--out",
            str(tmp_path / "out.json"),
        ],
    )

    cli_app.main()
    assert any("manifest.jsonl.lock" in path for path in captured["targets"])
    assert any("out.json.lock" in path for path in captured["targets"])


def test_cli_main_finalizes_run_bundle_as_fail_when_command_raises(monkeypatch):
    finalized = []

    def failing_cmd(_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_app, "cmd_analyze", failing_cmd)
    monkeypatch.setattr(cli_app, "initialize_run_bundle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli_app, "finalize_run_bundle", lambda run_id, command, status: finalized.append((run_id, command, status)))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "analyze",
            "--manifest",
            "/tmp/manifest.jsonl",
        ],
    )

    with pytest.raises(RuntimeError, match="boom"):
        cli_app.main()

    assert finalized
    assert finalized[-1][2] == "fail"
