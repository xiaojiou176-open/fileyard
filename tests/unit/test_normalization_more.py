import unicodedata
from pathlib import Path

from packages.domain import normalization


def test_normalize_kind_variants():
    assert normalization.normalize_kind("audio") == "音频"
    assert normalization.normalize_kind("screenshot") == "截图"
    assert normalization.normalize_kind("photo") == "照片"
    assert normalization.normalize_kind("document") == "文档"
    assert normalization.normalize_kind("") == "其他"


def test_normalize_category_fallback():
    cats = ["工作", "其他"]
    assert normalization.normalize_category("未知", cats) == "其他"
    assert normalization.normalize_category("工作", cats) == "工作"
    assert normalization.normalize_category("other", cats) == "其他"


def test_unique_path_increments(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    next_p = normalization.unique_path(p)
    assert next_p.name.startswith("a__2")


def test_safe_join_allows_root_equal(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    out = normalization.safe_join(root)
    assert out == root


def test_normalize_category_handles_empty_categories():
    assert normalization.normalize_category("未知", []) == "其他"
    assert normalization.normalize_category("", []) == "其他"


def test_normalize_categories_nfc_nfd_deduplicates():
    nfc = "旅行"
    nfd = unicodedata.normalize("NFD", nfc)
    out = normalization.normalize_categories([nfc, nfd])
    assert out.count("旅行") == 1


def test_normalize_categories_canonicalizes_other_alias():
    out = normalization.normalize_categories(["Work", "other", "misc"])
    assert out == ["工作", "其他"]


def test_slugify_blocks_windows_reserved_and_illegal_chars():
    val = normalization.slugify('CON<>:"/\\|?*   .')
    assert "CON" not in {val, val.lower()}
    assert all(ch not in val for ch in '<>:"/\\|?*')
