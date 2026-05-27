from __future__ import annotations

from pathlib import Path

from packages.application.collection_intelligence import _batch_hint, apply_collection_intelligence


def test_apply_collection_intelligence_v2_groups_by_parent_day_and_explains_batch_shape() -> None:
    rows = [
        {
            "id": "0",
            "original_path": "/tmp/trip/boarding-pass.png",
            "media_type": "image",
            "category": "旅行",
            "title": "boarding pass",
            "metadata": {"file_mtime": "2026-03-29T10:00:00"},
        },
        {
            "id": "1",
            "original_path": "/tmp/trip/hotel.pdf",
            "media_type": "pdf",
            "category": "旅行",
            "title": "hotel receipt",
            "metadata": {"file_mtime": "2026-03-29T11:00:00"},
        },
        {"id": "2", "original_path": "/tmp/work/c.pdf", "media_type": "pdf", "metadata": {"file_mtime": "2026-03-28T11:00:00"}},
    ]
    enriched, collections = apply_collection_intelligence(rows)
    assert len(collections) == 2
    assert enriched[0]["collection_id"] == enriched[1]["collection_id"]
    assert enriched[0]["collection_id"] != enriched[2]["collection_id"]
    assert any(collection.kind in {"travel_batch", "capture_batch"} for collection in collections)
    assert all(collection.next_step for collection in collections)
    assert all(isinstance(collection.explainability, tuple) for collection in collections)
    assert enriched[0]["collection_capture_day"] == "2026-03-29"
    assert enriched[0]["collection_source_root"] == "trip"
    assert "collection_next_step" in enriched[0]


def test_batch_hint_strips_numeric_suffix_without_regex_backtracking() -> None:
    hint = _batch_hint(
        Path("/tmp/IMG________________________________000123.jpg"),
        {},
        fallback="fallback",
    )
    assert hint == "fallback"
