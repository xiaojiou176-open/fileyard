import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

import pytest

from apps.cli import cli_app
from packages.domain import normalization
from packages.infrastructure import gemini_client, manifest_store


def test_gemini_shutdown_timeout_executor_resets_global(monkeypatch):
    class FakeExecutor:
        def __init__(self):
            self.args = None

        def shutdown(self, wait=False, cancel_futures=False):
            self.args = (wait, cancel_futures)

    fake = FakeExecutor()
    monkeypatch.setattr(gemini_client, "_TIMEOUT_EXECUTOR", fake)

    gemini_client._shutdown_timeout_executor()

    assert fake.args == (False, True)
    assert gemini_client._TIMEOUT_EXECUTOR is None


def test_gemini_shutdown_timeout_executor_when_none(monkeypatch):
    monkeypatch.setattr(gemini_client, "_TIMEOUT_EXECUTOR", None)
    monkeypatch.setattr(gemini_client, "_TIMEOUT_SEMAPHORE", object())
    gemini_client._shutdown_timeout_executor()
    assert gemini_client._TIMEOUT_EXECUTOR is None
    assert gemini_client._TIMEOUT_SEMAPHORE is None


def test_gemini_run_with_timeout_without_timeout():
    assert gemini_client._run_with_timeout(lambda: "ok", 0) == "ok"


def test_gemini_run_with_timeout_raises_when_semaphore_unavailable(monkeypatch):
    monkeypatch.setattr(gemini_client, "_get_timeout_executor", lambda: object())
    monkeypatch.setattr(gemini_client, "_TIMEOUT_SEMAPHORE", None)
    with pytest.raises(RuntimeError, match="timeout semaphore unavailable"):
        gemini_client._run_with_timeout(lambda: "ok", 0.1)


def test_gemini_run_with_timeout_releases_semaphore_when_elapsed_exceeds_timeout(monkeypatch):
    class _Sem:
        def __init__(self):
            self.released = 0

        def acquire(self, timeout=None):
            return True

        def release(self):
            self.released += 1

    sem = _Sem()
    ticks = iter([1.0, 2.0])
    monkeypatch.setattr(gemini_client, "_get_timeout_executor", lambda: object())
    monkeypatch.setattr(gemini_client, "_TIMEOUT_SEMAPHORE", sem)
    monkeypatch.setattr(gemini_client.time, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError):
        gemini_client._run_with_timeout(lambda: "ok", 0.5)
    assert sem.released == 1


def test_gemini_run_with_timeout_releases_semaphore_when_submit_raises(monkeypatch):
    class _Sem:
        def __init__(self):
            self.released = 0

        def acquire(self, timeout=None):
            return True

        def release(self):
            self.released += 1

    class _Exec:
        def submit(self, _fn):
            raise RuntimeError("submit boom")

    sem = _Sem()
    ticks = iter([1.0, 1.1])
    monkeypatch.setattr(gemini_client, "_get_timeout_executor", lambda: _Exec())
    monkeypatch.setattr(gemini_client, "_TIMEOUT_SEMAPHORE", sem)
    monkeypatch.setattr(gemini_client.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="submit boom"):
        gemini_client._run_with_timeout(lambda: "ok", 0.5)
    assert sem.released == 1


def test_gemini_status_code_from_response_attr():
    exc = RuntimeError("boom")
    exc.response = type("R", (), {"status_code": 503})()  # type: ignore[attr-defined]
    assert gemini_client._status_code_from_exc(exc) == 503


def test_gemini_build_client_success(monkeypatch):
    class DummyGenai:
        class Client:
            def __init__(self, api_key):
                self.api_key = api_key

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", lambda: (DummyGenai, object()))

    client = gemini_client.build_client("k-test")
    assert client.api_key == "k-test"


def test_gemini_build_config_strict_raises():
    class DummyTypes:
        class GenerateContentConfig:
            def __init__(self, **_kwargs):
                raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="response_mime_type"):
        gemini_client.build_config(DummyTypes, strict=True)


def test_gemini_extract_first_json_object_handles_escaped_quote_and_prefix_close():
    raw = '} junk {"k":"x\\"y"} tail'
    out = gemini_client._extract_first_json_object(raw)
    assert out == '{"k":"x\\"y"}'


def test_gemini_call_gemini_parse_failure_raises_nonretryable(monkeypatch):
    class DummyResp:
        text = "not-json"

    class DummyModels:
        def generate_content(self, **_kwargs):
            return DummyResp()

    class DummyClient:
        models = DummyModels()

    class DummyTypes:
        class GenerateContentConfig:
            def __init__(self, **_kwargs):
                pass

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", lambda: (None, DummyTypes))

    with pytest.raises(gemini_client.NonRetryableAIError):
        gemini_client.call_gemini(DummyClient(), model="m", image_part=object(), prompt="p")


def test_gemini_call_gemini_text_timeout_and_generic_error(monkeypatch):
    class DummyTypes:
        class GenerateContentConfig:
            def __init__(self, **_kwargs):
                pass

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", lambda: (None, DummyTypes))

    class DummyClient:
        models = type("M", (), {"generate_content": lambda *_args, **_kwargs: None})()

    monkeypatch.setattr(
        gemini_client,
        "_invoke_with_timeout_hints",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("t")),
    )
    with pytest.raises(RuntimeError, match="timed out"):
        gemini_client.call_gemini_text(DummyClient(), model="m", prompt="p", timeout_s=1.0)

    monkeypatch.setattr(
        gemini_client,
        "_invoke_with_timeout_hints",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError, match="request failed"):
        gemini_client.call_gemini_text(DummyClient(), model="m", prompt="p", timeout_s=1.0)


def test_gemini_call_gemini_text_no_config_and_candidate_parse_fail(monkeypatch):
    class DummyResp:
        text = None
        candidates = []

    class DummyModels:
        def generate_content(self, **_kwargs):
            return DummyResp()

    class DummyClient:
        models = DummyModels()

    class DummyTypes:
        class GenerateContentConfig:
            def __init__(self, **_kwargs):
                pass

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", lambda: (None, DummyTypes))
    monkeypatch.setattr(gemini_client, "build_config", lambda *_args, **_kwargs: None)

    with pytest.raises(gemini_client.NonRetryableAIError):
        gemini_client.call_gemini_text(DummyClient(), model="m", prompt="p")


def test_gemini_call_gemini_text_with_retry_stops_on_nonretryable(monkeypatch):
    monkeypatch.setattr(
        gemini_client,
        "call_gemini_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(gemini_client.NonRetryableAIError("bad")),
    )
    with pytest.raises(gemini_client.NonRetryableAIError):
        gemini_client.call_gemini_text_with_retry(
            client=object(),
            model="m",
            prompt="p",
            max_retries=5,
            retry_base_s=0.0,
            retry_max_s=0.0,
        )


def test_gemini_call_gemini_text_with_retry_max_retries_zero(monkeypatch):
    monkeypatch.setattr(
        gemini_client,
        "call_gemini_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError, match="boom"):
        gemini_client.call_gemini_text_with_retry(
            client=object(),
            model="m",
            prompt="p",
            max_retries=0,
            retry_base_s=0.0,
            retry_max_s=0.0,
        )


def test_gemini_safe_delete_file_empty_name_and_logger_branch():
    assert gemini_client.safe_delete_file(client=object(), name="") is True

    class DummyClient:
        files = type(
            "F",
            (),
            {"delete": lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no"))},
        )()

    logger = logging.getLogger("test-safe-delete")
    assert gemini_client.safe_delete_file(DummyClient(), "files/1", logger=logger, timeout_s=1.0) is False


def test_gemini_build_file_part_upload_timeout(monkeypatch, tmp_path: Path):
    p = tmp_path / "big.bin"
    p.write_bytes(b"hello")

    class DummyTypes:
        class Part:
            @staticmethod
            def from_bytes(*_args, **_kwargs):
                return object()

    monkeypatch.setattr(gemini_client, "_lazy_import_gemini", lambda: (None, DummyTypes))
    monkeypatch.setattr(gemini_client, "guess_mime", lambda _path: "application/octet-stream")
    monkeypatch.setattr(
        gemini_client,
        "_invoke_with_timeout_hints",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("upload timeout")),
    )

    dummy_client = type("C", (), {"files": type("F", (), {"upload": lambda *_a, **_k: None})()})()
    with pytest.raises(RuntimeError, match="file upload timed out"):
        gemini_client.build_file_part(p, client=dummy_client, inline_max_mb=0.0)


def test_manifest_store_fsync_dir_handles_os_open_error(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(manifest_store.os, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no")))
    assert manifest_store._fsync_dir(tmp_path) is None


def test_manifest_store_fsync_dir_handles_fsync_error(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(manifest_store.os, "open", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        manifest_store.os,
        "fsync",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fsync fail")),
    )
    monkeypatch.setattr(manifest_store.os, "close", lambda *_args, **_kwargs: None)

    assert manifest_store._fsync_dir(tmp_path) is None


def test_manifest_store_write_jsonl_cleans_partial_on_fsync_failure(monkeypatch, tmp_path: Path):
    out = tmp_path / "m.jsonl"
    partial = Path(str(out) + ".partial")

    monkeypatch.setattr(
        manifest_store.os,
        "fsync",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("boom")),
    )

    with pytest.raises(OSError):
        manifest_store.write_jsonl(out, [{"x": 1}])

    assert not partial.exists()


def test_manifest_store_load_schema_missing_file_non_strict(monkeypatch, tmp_path: Path):
    fake_root = tmp_path / "pkg" / "pipeline"
    fake_root.mkdir(parents=True)
    fake_file = fake_root / "manifest_store.py"
    fake_file.write_text("# fake", encoding="utf-8")

    monkeypatch.setattr(manifest_store, "_SCHEMA_CACHE", None)
    monkeypatch.setattr(manifest_store, "__file__", str(fake_file))
    monkeypatch.chdir(tmp_path)

    assert manifest_store._load_schema(strict=False) is None


def test_manifest_store_load_schema_invalid_json_paths(monkeypatch, tmp_path: Path):
    fake_root = tmp_path / "pkg" / "core" / "pipeline"
    fake_root.mkdir(parents=True)
    fake_file = fake_root / "manifest_store.py"
    fake_file.write_text("# fake", encoding="utf-8")
    schema_path = tmp_path / "contracts" / "runtime" / "manifest.schema.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text("{bad}", encoding="utf-8")

    monkeypatch.setattr(manifest_store, "_SCHEMA_CACHE", None)
    monkeypatch.setattr(manifest_store, "__file__", str(fake_file))
    monkeypatch.chdir(tmp_path)

    assert manifest_store._load_schema(strict=False) is None
    monkeypatch.setattr(manifest_store, "_SCHEMA_CACHE", None)
    with pytest.raises(RuntimeError, match="Manifest schema read failed"):
        manifest_store._load_schema(strict=True)


def test_manifest_store_validate_against_schema_extra_type_and_non_dict_property():
    manifest_store._validate_against_schema("x", {"type": "mystery"}, "$")

    schema = {"type": "object", "properties": {"x": "not-dict"}}
    manifest_store._validate_against_schema({"x": 1}, schema, "$")

    with pytest.raises(ValueError, match="field type mismatch"):
        manifest_store._validate_against_schema("x", {"type": ["number", "object"]}, "$")


def test_manifest_store_write_csv_cleans_partial_when_writer_fails(monkeypatch, tmp_path: Path):
    out = tmp_path / "x.csv"

    def fake_write(path, *_args, **_kwargs):
        path.write_text("tmp", encoding="utf-8")
        raise RuntimeError("csv fail")

    monkeypatch.setattr(manifest_store, "_write_csv_rows", fake_write)

    with pytest.raises(RuntimeError, match="csv fail"):
        manifest_store.write_csv(out, [{"path": "a", "ai": {}}])

    assert not Path(str(out) + ".partial").exists()


def test_manifest_store_write_csv_from_manifest_open_failure_without_partial(monkeypatch, tmp_path: Path):
    manifest = tmp_path / "m.jsonl"
    out = tmp_path / "out.csv"
    manifest.write_text(json.dumps({"path": "a", "ai": {}}, ensure_ascii=False) + "\n", encoding="utf-8")

    real_open = Path.open
    partial = Path(str(out) + ".partial")

    def fake_open(self, *args, **kwargs):
        if self == partial:
            raise OSError("open fail")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fake_open)

    with pytest.raises(OSError, match="open fail"):
        manifest_store.write_csv_from_manifest(manifest, out, validate=False)

    assert not partial.exists()


def test_normalization_more_edges(tmp_path: Path):
    assert normalization.normalize_kind("unknown-kind") == "其他"
    assert normalization.slugify("", max_len=0) == "未命名"
    assert normalization.slugify("***", max_len=0) == "未命名"

    row = {"exif_datetime": "not-iso", "file_mtime": "2026-01-01T00:00:00"}
    ts = normalization.choose_timestamp(row)
    expected = normalization.to_seattle(dt.datetime.fromisoformat(row["file_mtime"]).replace(tzinfo=dt.timezone.utc))
    assert ts == expected

    with pytest.raises(ValueError, match="unsafe absolute path"):
        normalization.safe_join(tmp_path, "/abs/path")

    p = tmp_path / "a.txt"
    p.write_text("1", encoding="utf-8")
    (tmp_path / "a__2.txt").write_text("2", encoding="utf-8")
    assert normalization.unique_path(p).name == "a__3.txt"


def test_cli_helpers_cover_edges(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FILEYARD_ENABLE_TEST_HOOKS", "1")
    assert cli_app._is_test_hooks_enabled() is True

    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("FILEYARD_WORKSPACE_ROOT", str(workspace_root))
    assert cli_app._default_report_out() == str(workspace_root / ".fileyard" / "artifacts" / "report" / "report_summary.json")

    assert "其他" in cli_app._parse_categories(("工作", "旅行"))

    parser = argparse.ArgumentParser()
    args = argparse.Namespace(manifest="")
    with pytest.raises(SystemExit) as exc:
        cli_app._require_non_empty_arg(parser, args, "analyze", "manifest")
    assert exc.value.code == 2

    assert cli_app._is_bool(True) is True
    assert cli_app._is_int(True) is False
    assert cli_app._is_number(1.5) is True
    assert cli_app._is_str_or_str_list(["a", 1]) is False
    assert cli_app._resolve_optional_path("") is None


def test_cli_validate_output_conflicts_all_paths(tmp_path: Path):
    parser = argparse.ArgumentParser()

    args_analyze = argparse.Namespace(cmd="analyze", manifest=str(tmp_path / "m.jsonl"), csv="", report="")
    cli_app._validate_output_path_conflicts(parser, args_analyze)

    same = str(tmp_path / "same")
    with pytest.raises(SystemExit) as exc:
        cli_app._validate_output_path_conflicts(
            parser,
            argparse.Namespace(cmd="analyze", manifest=same, csv=same, report=""),
        )
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        cli_app._validate_output_path_conflicts(
            parser,
            argparse.Namespace(
                cmd="analyze",
                manifest=same,
                csv="",
                report=same,
            ),
        )
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        cli_app._validate_output_path_conflicts(
            parser,
            argparse.Namespace(
                cmd="apply",
                manifest=same,
                out_manifest=str(tmp_path / "other.jsonl"),
                report=same,
                rollback_manifest="",
            ),
        )
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        cli_app._validate_output_path_conflicts(
            parser,
            argparse.Namespace(
                cmd="apply",
                manifest=same,
                out_manifest="",
                report="",
                rollback_manifest=same,
            ),
        )
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        cli_app._validate_output_path_conflicts(
            parser,
            argparse.Namespace(cmd="report", manifest=same, out=same),
        )
    assert exc.value.code == 2


def test_cli_main_config_load_fail_logs_and_exits(monkeypatch, tmp_path: Path):
    events = []
    monkeypatch.setattr(cli_app, "load_config", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad cfg")))
    monkeypatch.setattr(cli_app, "setup_logger", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        cli_app,
        "log_event",
        lambda *_args, **kwargs: events.append(kwargs.get("error_code")),
    )

    monkeypatch.setattr(sys, "argv", ["fileyard", "--config", str(tmp_path / "bad.toml"), "report", "--manifest", "m", "--out", "o"])

    with pytest.raises(SystemExit, match="Failed to load config"):
        cli_app.main()

    assert events and events[0] == cli_app.ErrorCode.CONFIG_INVALID.value


def test_cli_main_invalid_crash_inject(monkeypatch):
    monkeypatch.setattr(cli_app, "validate_config", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr(cli_app, "_is_test_hooks_enabled", lambda: True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "apply",
            "--manifest",
            "/tmp/m.jsonl",
            "--output",
            "/tmp/o",
            "--crash-inject",
            "bad-point",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli_app.main()
    assert exc.value.code == 2


def test_cli_main_collects_analyze_and_apply_lock_targets(monkeypatch, tmp_path: Path):
    acquired = []

    monkeypatch.setattr(cli_app, "validate_config", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr(cli_app, "setup_logger", lambda *_args, **_kwargs: object())

    def _acquire_file_lock(p):
        acquired.append(str(p))
        return 1

    monkeypatch.setattr(cli_app, "acquire_file_lock", _acquire_file_lock)
    monkeypatch.setattr(cli_app, "release_file_lock", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli_app, "cmd_analyze", lambda _args: None)
    monkeypatch.setattr(cli_app, "cmd_apply", lambda _args: None)

    manifest = tmp_path / "m.jsonl"
    csv = tmp_path / "m.csv"
    report = tmp_path / "r.json"
    rollback_manifest = tmp_path / "rb.jsonl"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "analyze",
            "--manifest",
            str(manifest),
            "--csv",
            str(csv),
            "--report",
            str(report),
        ],
    )
    cli_app.main()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "apply",
            "--manifest",
            str(manifest),
            "--output",
            str(tmp_path / "out"),
            "--report",
            str(report),
            "--rollback-manifest",
            str(rollback_manifest),
        ],
    )
    cli_app.main()

    joined = "\n".join(acquired)
    assert str(Path(str(csv) + ".lock")) in joined
    assert str(Path(str(report) + ".lock")) in joined
    assert str(Path(str(rollback_manifest) + ".lock")) in joined


def test_cli_main_lock_fail_releases_previously_acquired(monkeypatch, tmp_path: Path):
    released = []
    call = {"n": 0}

    def fake_acquire(path):
        call["n"] += 1
        if call["n"] == 1:
            return 7
        raise RuntimeError("lock boom")

    monkeypatch.setattr(cli_app, "validate_config", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr(cli_app, "setup_logger", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(cli_app, "log_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli_app, "acquire_file_lock", fake_acquire)
    monkeypatch.setattr(cli_app, "release_file_lock", lambda path, fd: released.append((str(path), fd)))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fileyard",
            "report",
            "--manifest",
            str(tmp_path / "m.jsonl"),
            "--out",
            str(tmp_path / "r.json"),
        ],
    )

    with pytest.raises(SystemExit, match="Failed to acquire task lock"):
        cli_app.main()

    assert released
    assert released[0][1] == 7
