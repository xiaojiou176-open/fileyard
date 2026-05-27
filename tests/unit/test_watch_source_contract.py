from __future__ import annotations

from pathlib import Path

from packages.application.inbox_watch import scan_watch_sources_once
from packages.infrastructure.watch_source_store import WatchSource


def test_scan_watch_sources_once_returns_review_only_batches(tmp_path: Path) -> None:
    source_root = tmp_path / "watch"
    source_root.mkdir()
    (source_root / "a.png").write_bytes(b"img")
    batches = scan_watch_sources_once(
        [
            WatchSource(
                id="source-1",
                name="Desktop intake",
                input_root=str(source_root),
                enabled=True,
                strategy_pack_id="travel",
            )
        ]
    )
    assert len(batches) == 1
    assert batches[0].file_count == 1
    assert batches[0].watch_source_id == "source-1"
    assert batches[0].source_name == "Desktop intake"
    assert batches[0].strategy_pack_id == "travel"
    assert batches[0].source_name == "Desktop intake"
    assert batches[0].strategy_pack_id == "travel"


def test_scan_watch_sources_once_skips_disabled_missing_and_empty_sources(tmp_path: Path) -> None:
    source_root = tmp_path / "watch"
    source_root.mkdir()
    disabled = WatchSource(id="disabled", name="Disabled", input_root=str(source_root), enabled=False)
    missing = WatchSource(id="missing", name="Missing", input_root=str(tmp_path / "missing"), enabled=True)
    empty = WatchSource(id="empty", name="Empty", input_root=str(source_root), enabled=True)
    assert scan_watch_sources_once([disabled, missing, empty]) == []
    assert WatchSource(id="x", name="Name", input_root="/tmp", enabled=True).to_dict()["name"] == "Name"
