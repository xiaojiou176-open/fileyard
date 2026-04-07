import argparse
from pathlib import Path

import pytest

from packages.application import apply_changes
from packages.domain.pipeline_config import KEY_ERROR_CODE, ErrorCode
from packages.infrastructure.manifest_store import read_jsonl_list, write_jsonl


def _make_row(src: Path, input_root: Path, sha1: str | None = None) -> dict:
    val = sha1 or apply_changes.sha1_file(src)
    return {
        "schema_version": 2,
        "path": str(src),
        "input_root": str(input_root),
        "sha1": val,
        "hash8": val[:8],
        "file_mtime": "2025-01-01T12:00:00",
        "media_type": "image",
        "ai": {
            "kind": "截图",
            "category": "工作",
            "title": "测试",
            "tags": [],
            "confidence": 1,
            "notes": "",
        },
        "error": "",
    }


def _apply_args(manifest: Path, input_root: Path, output_root: Path, **extra):
    base = dict(
        manifest=str(manifest),
        output=str(output_root),
        categories=["工作", "其他"],
        dry_run=False,
        out_manifest="",
        dedupe=True,
        input_root=str(input_root),
        verify_sha1=False,
        fsync_interval=0,
        durability="none",
        resume=True,
        retry_errors=False,
        log_level="INFO",
        log_json=False,
        run_id="",
        generator_version="",
        report="",
        rollback_manifest="",
    )
    base.update(extra)
    return argparse.Namespace(**base)


def test_build_rollback_from_manifest_filters_and_projects_fields():
    rows = [
        {
            "status": "applied",
            "path": "/tmp/src-a",
            "new_path": "/tmp/dst-a",
            "media_type": "image",
            "applied_at": "2025-01-01T00:00:00",
            "schema_version": 2,
        },
        {
            "status": "duplicate",
            "path": "/tmp/src-b",
            "new_path": "/tmp/dst-b",
            "media_type": "audio",
        },
        {"status": "error", "path": "/tmp/src-c", "new_path": "/tmp/dst-c"},
        {"status": "applied", "path": "", "new_path": "/tmp/dst-d"},
        {"status": "applied", "path": "/tmp/src-e", "new_path": ""},
    ]

    rebuilt = apply_changes._build_rollback_from_manifest(rows)
    assert len(rebuilt) == 2
    assert rebuilt[0]["path"] == "/tmp/src-a"
    assert rebuilt[0]["new_path"] == "/tmp/dst-a"
    assert rebuilt[0]["schema_version"] == 2
    assert rebuilt[1]["status"] == "duplicate"
    assert rebuilt[1]["media_type"] == "audio"


def test_apply_wal_invalid_json_is_tolerated(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    src = input_root / "a.png"
    src.write_bytes(b"x")

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_make_row(src, input_root)])
    wal = Path(str(manifest) + ".apply.wal.json")
    wal.write_text("{not json", encoding="utf-8")

    args = _apply_args(manifest, input_root, output_root, dry_run=True)
    apply_changes.cmd_apply(args)

    assert manifest.exists()
    assert not wal.exists()


def test_apply_wal_recovery_fail_exits(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    src = input_root / "a.png"
    src.write_bytes(b"x")

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_make_row(src, input_root)])
    partial = Path(str(manifest) + ".partial")
    partial.write_text("x\n", encoding="utf-8")
    wal = Path(str(manifest) + ".apply.wal.json")
    wal.write_text('{"phase":"moving"}', encoding="utf-8")

    original_replace = apply_changes.Path.replace

    def _boom_replace(self, target):
        if str(self).endswith(".partial"):
            raise RuntimeError("replace fail")
        return original_replace(self, target)

    monkeypatch.setattr(apply_changes.Path, "replace", _boom_replace)
    with pytest.raises(SystemExit, match="WAL recovery failed"):
        apply_changes.cmd_apply(_apply_args(manifest, input_root, output_root, dry_run=True))


def test_apply_rollback_manifest_write_fail_exits(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    src = input_root / "a.png"
    src.write_bytes(b"x")

    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_make_row(src, input_root)])

    def _boom_write(_fh, _row, fsync=False):
        raise RuntimeError("rollback write fail")

    monkeypatch.setattr(apply_changes, "write_jsonl_line", _boom_write)
    with pytest.raises(SystemExit, match="Failed to write rollback manifest"):
        apply_changes.cmd_apply(_apply_args(manifest, input_root, output_root))


def test_apply_report_write_fail_exits(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    src = input_root / "a.png"
    src.write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_make_row(src, input_root)])

    monkeypatch.setattr(apply_changes, "write_report", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("r")))
    with pytest.raises(SystemExit, match="Failed to write report"):
        apply_changes.cmd_apply(_apply_args(manifest, input_root, output_root, report=str(tmp_path / "report.json")))


def test_apply_dedupe_path_fail_sets_error(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    a = input_root / "a.png"
    b = input_root / "b.png"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    sha = apply_changes.sha1_file(a)
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_make_row(a, input_root, sha), _make_row(b, input_root, sha)])

    original_safe_join = apply_changes.safe_join

    def _safe_join_for_dedupe(*args):
        if len(args) >= 2 and str(args[1]) == "duplicates":
            raise RuntimeError("bad path")
        return original_safe_join(*args)

    monkeypatch.setattr(apply_changes, "safe_join", _safe_join_for_dedupe)
    apply_changes.cmd_apply(_apply_args(manifest, input_root, output_root, dry_run=True))

    rows = read_jsonl_list(manifest, validate=True)
    assert rows[1].get(KEY_ERROR_CODE) == ErrorCode.DEDUPE_PATH_FAIL.value


def test_apply_dedupe_dry_run_marks_skipped(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    a = input_root / "a.png"
    b = input_root / "b.png"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    sha = apply_changes.sha1_file(a)
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_make_row(a, input_root, sha), _make_row(b, input_root, sha)])

    apply_changes.cmd_apply(_apply_args(manifest, input_root, output_root, dry_run=True))
    rows = read_jsonl_list(manifest, validate=True)
    assert rows[1].get("status") == "skipped"
    assert rows[1].get("status_reason") == "dry_run_dedupe"
    assert rows[1].get("new_path")
    assert rows[1].get("dedupe_of")


def test_apply_preserve_rollback_crash_fail_path(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    src = input_root / "a.png"
    src.write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_make_row(src, input_root)])

    def _boom_write(_fh, _row, fsync=False):
        raise RuntimeError("fail write")

    original_preserve = apply_changes._preserve_crash_file

    def _preserve_with_rollback_fail(path: Path):
        if str(path).endswith(".rollback.jsonl.partial"):
            raise RuntimeError("cannot preserve rollback partial")
        return original_preserve(path)

    monkeypatch.setattr(apply_changes, "write_jsonl_line", _boom_write)
    monkeypatch.setattr(apply_changes, "_preserve_crash_file", _preserve_with_rollback_fail)
    with pytest.raises(SystemExit, match="Failed to write rollback manifest") as exc:
        apply_changes.cmd_apply(_apply_args(manifest, input_root, output_root))
    assert isinstance(exc.value.code, str)
    assert "fail write" in exc.value.code

    assert list(tmp_path.glob("manifest.jsonl.partial.crash-*"))


def test_apply_fsync_interval_negative_clamped(monkeypatch, tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    src = input_root / "a.png"
    src.write_bytes(b"x")
    manifest = tmp_path / "manifest.jsonl"
    write_jsonl(manifest, [_make_row(src, input_root)])

    monkeypatch.setattr(apply_changes, "resolve_fsync_interval", lambda *_args, **_kwargs: -3)
    flags = []

    def _capture_write(_fh, _row, fsync=False):
        flags.append(fsync)

    monkeypatch.setattr(apply_changes, "write_jsonl_line", _capture_write)
    apply_changes.cmd_apply(_apply_args(manifest, input_root, output_root, dry_run=True))
    assert flags == [False]


def test_rollback_path_resolve_fail_is_skipped(monkeypatch, tmp_path: Path):
    src = tmp_path / "moved.txt"
    src.write_text("x", encoding="utf-8")
    dst = tmp_path / "orig.txt"
    manifest = tmp_path / "rollback_manifest.jsonl"
    write_jsonl(manifest, [{"path": str(dst), "new_path": str(src), "media_type": "image"}])

    original_resolve = apply_changes.Path.resolve

    def _fake_resolve(self):
        if str(self).endswith("moved.txt"):
            raise RuntimeError("resolve fail")
        return original_resolve(self)

    monkeypatch.setattr(apply_changes.Path, "resolve", _fake_resolve)
    apply_changes.cmd_rollback(argparse.Namespace(manifest=str(manifest), dry_run=False, overwrite=False, allowed_root=str(tmp_path)))
    assert src.exists()
    assert not dst.exists()


def test_rollback_dry_run_and_move_fail_branches(monkeypatch, tmp_path: Path):
    src1 = tmp_path / "moved1.txt"
    src2 = tmp_path / "moved2.txt"
    src1.write_text("a", encoding="utf-8")
    src2.write_text("b", encoding="utf-8")
    dst1 = tmp_path / "orig1.txt"
    dst2 = tmp_path / "orig2.txt"

    manifest = tmp_path / "rollback_manifest.jsonl"
    write_jsonl(
        manifest,
        [
            {"path": str(dst1), "new_path": str(src1), "media_type": "image"},
            {"path": str(dst2), "new_path": str(src2), "media_type": "image"},
        ],
    )

    apply_changes.cmd_rollback(argparse.Namespace(manifest=str(manifest), dry_run=True, overwrite=False, allowed_root=str(tmp_path)))
    assert src1.exists()
    assert not dst1.exists()

    def _exdev_replace(self, target):
        raise OSError(18, "Cross-device link")

    def _boom_move(*_args, **_kwargs):
        raise RuntimeError("rollback move fail")

    monkeypatch.setattr(apply_changes.Path, "replace", _exdev_replace)
    monkeypatch.setattr(apply_changes.shutil, "move", _boom_move)
    apply_changes.cmd_rollback(argparse.Namespace(manifest=str(manifest), dry_run=False, overwrite=False, allowed_root=str(tmp_path)))
    assert src2.exists()
    assert not dst2.exists()
