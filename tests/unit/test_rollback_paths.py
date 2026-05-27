import json
from pathlib import Path

import pytest
from packages.application.apply_changes import cmd_rollback


def test_rollback_overwrite(tmp_path: Path):
    original = tmp_path / "orig.txt"
    moved = tmp_path / "moved.txt"

    original.write_text("old", encoding="utf-8")
    moved.write_text("new", encoding="utf-8")

    row = {
        "path": str(original),
        "new_path": str(moved),
        "media_type": "image",
    }
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")

    args = type(
        "Args",
        (),
        {
            "manifest": str(manifest),
            "dry_run": False,
            "overwrite": False,
            "allowed_root": str(tmp_path),
        },
    )
    cmd_rollback(args)
    assert moved.exists()
    assert original.read_text(encoding="utf-8") == "old"

    args2 = type(
        "Args",
        (),
        {
            "manifest": str(manifest),
            "dry_run": False,
            "overwrite": True,
            "allowed_root": str(tmp_path),
        },
    )
    cmd_rollback(args2)
    assert original.read_text(encoding="utf-8") == "new"
    assert not moved.exists()


def test_rollback_overwrite_dry_run_keeps_target(tmp_path: Path):
    original = tmp_path / "orig.txt"
    moved = tmp_path / "moved.txt"
    original.write_text("old", encoding="utf-8")
    moved.write_text("new", encoding="utf-8")

    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps({"path": str(original), "new_path": str(moved), "media_type": "image"}) + "\n",
        encoding="utf-8",
    )

    args = type(
        "Args",
        (),
        {
            "manifest": str(manifest),
            "dry_run": True,
            "overwrite": True,
            "allowed_root": str(tmp_path),
        },
    )
    cmd_rollback(args)

    assert original.read_text(encoding="utf-8") == "old"
    assert moved.read_text(encoding="utf-8") == "new"


def test_rollback_rejects_filesystem_root_allowed_root(tmp_path: Path):
    original = tmp_path / "orig.txt"
    moved = tmp_path / "moved.txt"
    original.write_text("old", encoding="utf-8")
    moved.write_text("new", encoding="utf-8")

    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps({"path": str(original), "new_path": str(moved), "media_type": "image"}) + "\n",
        encoding="utf-8",
    )

    fs_root = str(Path(tmp_path.anchor).resolve())
    args = type(
        "Args",
        (),
        {
            "manifest": str(manifest),
            "dry_run": False,
            "overwrite": True,
            "allowed_root": fs_root,
        },
    )

    with pytest.raises(SystemExit, match="rollback refuses to use the filesystem root as --allowed-root"):
        cmd_rollback(args)
