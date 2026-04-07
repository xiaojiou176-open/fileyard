import datetime as dt
from pathlib import Path

import pytest
from packages.application.apply_changes import build_destination

from packages.application import apply_changes, apply_safety_helpers
from packages.domain.pipeline_config import MEDIA_AUDIO, MEDIA_PDF


def _row(path: Path, media_type: str, kind: str, category: str):
    return {
        "path": str(path),
        "file_mtime": dt.datetime(2025, 1, 1, 12, 0, 0).isoformat(),
        "media_type": media_type,
        "hash8": "abcd1234",
        "ai": {"kind": kind, "category": category, "title": "测试"},
    }


def test_build_destination_audio_and_doc(tmp_path: Path):
    out = tmp_path / "out"

    row_audio = _row(tmp_path / "a.jpeg", MEDIA_AUDIO, "音频", "工作")
    folder_a, filename_a = build_destination(row_audio, out, ["工作", "其他"])
    assert folder_a == out / "音频" / "工作"
    assert filename_a.endswith(".jpg")

    row_doc = _row(tmp_path / "b.pdf", MEDIA_PDF, "文档", "文档")
    folder_d, filename_d = build_destination(row_doc, out, ["文档", "其他"])
    assert folder_d == out / "文档" / "文档"
    assert filename_d.endswith(".pdf")


def test_build_destination_truncates_overlong_filename(tmp_path: Path):
    out = tmp_path / "out"
    row = _row(tmp_path / "a.png", "image", "截图", "工作")
    row["ai"]["title"] = "x" * 500
    _folder, filename = build_destination(row, out, ["工作", "其他"])
    assert len(filename) <= 240
    assert filename.endswith(".png")


def test_is_within_root_returns_false_and_logs_when_resolve_fails(monkeypatch, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    child = root / "nested" / "a.txt"
    child.parent.mkdir(parents=True)
    child.write_text("ok", encoding="utf-8")

    captured = {}

    def _capture(_logger, _level, event, _message, **fields):
        captured["event"] = event
        captured["fields"] = fields

    monkeypatch.setattr(apply_changes, "log_event", _capture)

    def _boom_resolve(_self: Path) -> Path:
        raise RuntimeError("resolve failed")

    monkeypatch.setattr(apply_changes.Path, "resolve", _boom_resolve)
    assert apply_changes._is_within_root(child, root) is False

    assert captured["event"] == "path_boundary_check_failed"
    assert captured["fields"]["error_type"] == "RuntimeError"
    assert captured["fields"]["path_name"] == "a.txt"
    assert captured["fields"]["root_name"] == "root"


def test_is_within_root_true_when_path_is_under_root(tmp_path: Path):
    root = tmp_path / "root"
    child = root / "nested" / "a.txt"
    child.parent.mkdir(parents=True)
    child.write_text("ok", encoding="utf-8")
    assert apply_changes._is_within_root(child, root) is True


def test_is_within_root_false_when_path_is_outside_root(tmp_path: Path):
    root = tmp_path / "root"
    outside = tmp_path / "outside.txt"
    root.mkdir()
    outside.write_text("ok", encoding="utf-8")
    assert apply_changes._is_within_root(outside, root) is False


def test_apply_safety_helpers_remaining_branches(tmp_path: Path):
    path = tmp_path / "state.jsonl"
    path.write_text('{"path":"x","new_path":"y","run_id":"z","media_type":"image"}\n', encoding="utf-8")
    assert apply_changes._is_valid_jsonl_file(path) is True

    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text("{bad-json}\n", encoding="utf-8")
    assert apply_changes._is_valid_jsonl_file(invalid) is False
    assert apply_changes._resolve_if_exists(str(tmp_path / "missing.txt")) is None
    assert apply_changes._is_filesystem_root(Path("/")) is True
    assert apply_changes._is_filesystem_root(tmp_path) is False

    backup_target = tmp_path / "report.json"
    backup_target.write_text("x", encoding="utf-8")
    first = apply_changes._next_overwrite_backup_path(backup_target)
    first.write_text("occupied", encoding="utf-8")
    second = apply_changes._next_overwrite_backup_path(backup_target)
    assert first != second

    crash_target = tmp_path / "crash.json"
    crash_target.write_text("boom", encoding="utf-8")
    preserved = apply_changes._preserve_crash_file(crash_target)
    assert preserved.exists()

    moved_src = tmp_path / "move.txt"
    moved_src.write_text("ok", encoding="utf-8")
    moved_dst = tmp_path / "move-dst.txt"
    apply_changes._safe_move_with_verification(moved_src, moved_dst, moved_src.resolve())
    assert moved_dst.exists()

    changed = tmp_path / "changed.txt"
    changed.write_text("changed", encoding="utf-8")
    with pytest.raises(RuntimeError):
        apply_safety_helpers._safe_move_with_verification(changed, moved_dst, moved_dst.resolve())

    missing = tmp_path / "missing.txt"
    with pytest.raises(RuntimeError):
        apply_safety_helpers._safe_move_with_verification(missing, moved_dst, missing)

    not_file = tmp_path / "dir"
    not_file.mkdir()
    with pytest.raises(RuntimeError):
        apply_safety_helpers._safe_move_with_verification(not_file, moved_dst, not_file.resolve())
