import pytest

from packages.infrastructure.manifest_store import attach_manifest_metadata, detect_schema_versions


def test_attach_manifest_metadata():
    row = {"path": "x"}
    attach_manifest_metadata(row, run_id="run-1", generator_version="1.0.0", schema_version=2)
    assert row["schema_version"] == 2
    assert row["run_id"] == "run-1"
    assert row["generator_version"] == "1.0.0"
    assert row["status"] == "pending"


def test_detect_schema_versions():
    rows = [
        {"schema_version": 1},
        {"schema_version": "2"},
        {"schema_version": 2},
    ]
    assert detect_schema_versions(rows) == [1, 2]


def test_attach_manifest_metadata_rejects_invalid_run_id():
    row = {"path": "x"}
    with pytest.raises(ValueError):
        attach_manifest_metadata(row, run_id="??", generator_version="1.0.0", schema_version=2)
