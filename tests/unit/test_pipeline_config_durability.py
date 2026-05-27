from packages.domain.pipeline_config import (
    CATEGORY_COMPATIBILITY_ALIASES,
    CATEGORY_OTHER,
    DEFAULT_MANIFEST_FSYNC_INTERVAL,
    KIND_COMPATIBILITY_ALIASES,
    ImageKind,
    resolve_fsync_interval,
)


def test_resolve_fsync_interval_override():
    assert resolve_fsync_interval("batch", 7) == 7


def test_resolve_fsync_interval_durability():
    assert resolve_fsync_interval("none", 0) == 0
    assert resolve_fsync_interval("sync", 0) == 1
    assert resolve_fsync_interval("batch", 0) == DEFAULT_MANIFEST_FSYNC_INTERVAL


def test_compatibility_aliases_keep_localized_product_values():
    assert CATEGORY_COMPATIBILITY_ALIASES["other"] == CATEGORY_OTHER
    assert KIND_COMPATIBILITY_ALIASES["document"] == ImageKind.DOCUMENT.value
    assert KIND_COMPATIBILITY_ALIASES["audio"] == ImageKind.AUDIO.value
