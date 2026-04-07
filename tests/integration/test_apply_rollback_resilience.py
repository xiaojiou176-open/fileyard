import json
import sys
from pathlib import Path

import pytest

from apps.cli import cli_app


def _read_manifest_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", argv)
    cli_app.main()


def _prepare_offline_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    media_path = input_dir / "截图_集成恢复.png"
    media_path.write_bytes(b"offline-integration-media")
    manifest_path = tmp_path / "manifest.jsonl"

    _run_cli(
        monkeypatch,
        [
            "movi_organizer",
            "analyze",
            "--input",
            str(input_dir),
            "--manifest",
            str(manifest_path),
            "--offline",
            "--workers",
            "1",
            "--durability",
            "none",
        ],
    )
    return input_dir, output_dir, manifest_path


def test_apply_trusted_manifest_root_allowlist_boundary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_dir, output_dir, manifest_path = _prepare_offline_manifest(monkeypatch, tmp_path)
    allow_root = tmp_path / "allowlist_only"
    allow_root.mkdir()

    _run_cli(
        monkeypatch,
        [
            "movi_organizer",
            "apply",
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_dir),
            "--durability",
            "none",
            "--trust-manifest-input-root",
            "--manifest-input-root-allowlist",
            str(allow_root),
        ],
    )

    rows = _read_manifest_rows(manifest_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert "manifest input_root is outside the allowlist" in rows[0]["error"]
    assert Path(rows[0]["path"]).exists()
    assert not rows[0].get("new_path")
    assert not list(output_dir.rglob("*.*"))
    assert input_dir.exists()


def test_rollback_strict_integrity_requires_hmac_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_dir, output_dir, manifest_path = _prepare_offline_manifest(monkeypatch, tmp_path)
    rollback_manifest = tmp_path / "rollback.jsonl"

    _run_cli(
        monkeypatch,
        [
            "movi_organizer",
            "apply",
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_dir),
            "--input-root",
            str(input_dir),
            "--durability",
            "none",
            "--rollback-manifest",
            str(rollback_manifest),
        ],
    )

    rows = _read_manifest_rows(manifest_path)
    assert len(rows) == 1
    moved_path = Path(rows[0]["new_path"])
    assert moved_path.exists()
    assert rollback_manifest.exists()
    monkeypatch.delenv("MOVI_ROLLBACK_HMAC_KEY", raising=False)

    with pytest.raises(SystemExit, match="strict_integrity=true requires MOVI_ROLLBACK_HMAC_KEY"):
        _run_cli(
            monkeypatch,
            [
                "movi_organizer",
                "rollback",
                "--manifest",
                str(rollback_manifest),
                "--allowed-root",
                str(tmp_path),
                "--strict-integrity",
            ],
        )

    assert moved_path.exists()
    assert not Path(rows[0]["path"]).exists()


def test_apply_crash_then_resume_recovers_rollback_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_dir, output_dir, manifest_path = _prepare_offline_manifest(monkeypatch, tmp_path)
    wal_path = Path(str(manifest_path) + ".apply.wal.json")
    rollback_manifest = Path(str(manifest_path) + ".rollback.jsonl")

    monkeypatch.setenv("MOVI_ENABLE_TEST_HOOKS", "1")
    monkeypatch.setenv("MOVI_APPLY_CRASH_AT", "after_manifest_before_rollback_commit")
    with pytest.raises(RuntimeError, match="Crash injected at after_manifest_before_rollback_commit"):
        _run_cli(
            monkeypatch,
            [
                "movi_organizer",
                "apply",
                "--manifest",
                str(manifest_path),
                "--output",
                str(output_dir),
                "--input-root",
                str(input_dir),
                "--durability",
                "none",
            ],
        )

    assert wal_path.exists()
    monkeypatch.delenv("MOVI_APPLY_CRASH_AT", raising=False)

    _run_cli(
        monkeypatch,
        [
            "movi_organizer",
            "apply",
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_dir),
            "--input-root",
            str(input_dir),
            "--durability",
            "none",
        ],
    )

    rows = _read_manifest_rows(manifest_path)
    assert len(rows) == 1
    moved_path = Path(rows[0]["new_path"])
    assert rows[0]["status"] in {"applied", "duplicate"}
    assert moved_path.exists()
    assert not Path(rows[0]["path"]).exists()
    assert rollback_manifest.exists()
    assert not wal_path.exists()
