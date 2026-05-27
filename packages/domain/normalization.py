# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from pathlib import Path
from typing import Literal, Sequence

from packages.domain.core_utils import to_seattle
from packages.domain.pipeline_config import (
    CATEGORY_COMPATIBILITY_ALIASES,
    CATEGORY_OTHER,
    KIND_COMPATIBILITY_ALIASES,
)

_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
}
_WINDOWS_ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_NFC_NORMALIZE: Literal["NFC"] = "NFC"
DEFAULT_LOCALIZED_SLUG_FALLBACK = "未命名"
# Product-localized fallback for generated filenames. This is user-facing output,
# not a maintainer-facing diagnostic surface.


def _normalize_text_nfc(value: str) -> str:
    return unicodedata.normalize(_NFC_NORMALIZE, str(value or ""))


def _normalize_categories_input(categories: Sequence[str]) -> list[str]:
    normalized = normalize_categories(categories)
    if not normalized:
        return [CATEGORY_OTHER]
    return normalized


def _canonicalize_category_value(value: str) -> str:
    lowered = value.casefold()
    return CATEGORY_COMPATIBILITY_ALIASES.get(lowered, value)


def normalize_categories(raw: Sequence[str]) -> list[str]:
    cleaned: list[str] = []
    for item in raw:
        val = _normalize_text_nfc(str(item).strip())
        val = _canonicalize_category_value(val)
        if not val:
            continue
        if val not in cleaned:
            cleaned.append(val)
    if CATEGORY_OTHER not in cleaned:
        cleaned.append(CATEGORY_OTHER)
    if not cleaned:
        cleaned = [CATEGORY_OTHER]
    return cleaned


def normalize_kind(value: str) -> str:
    if not value:
        return CATEGORY_OTHER
    val = _normalize_text_nfc(value.strip())
    canonical = KIND_COMPATIBILITY_ALIASES.get(val) or KIND_COMPATIBILITY_ALIASES.get(val.casefold())
    if canonical:
        return canonical
    return CATEGORY_OTHER


def normalize_category(value: str, categories: Sequence[str]) -> str:
    normalized_categories = _normalize_categories_input(categories)
    default_category = CATEGORY_OTHER if CATEGORY_OTHER in normalized_categories else normalized_categories[0]
    if not value:
        return default_category
    val = _normalize_text_nfc(value.strip())
    lookup: dict[str, str] = {}
    for category in normalized_categories:
        lookup[category] = category
        lookup[category.casefold()] = category
    if CATEGORY_OTHER in normalized_categories:
        for alias, compatible_category in CATEGORY_COMPATIBILITY_ALIASES.items():
            lookup[alias] = compatible_category
            lookup[alias.casefold()] = compatible_category
    canonical_category: str | None = lookup.get(val) or lookup.get(val.casefold())
    if canonical_category is not None:
        return canonical_category
    return default_category


def slugify(text: str, max_len: int = 80) -> str:
    if not text:
        return DEFAULT_LOCALIZED_SLUG_FALLBACK
    text = _normalize_text_nfc(text.strip())
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", text, flags=re.UNICODE)
    text = _WINDOWS_ILLEGAL_CHARS_RE.sub("_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    text = text.strip(" .")
    if text.lower() in _WINDOWS_RESERVED_NAMES:
        text = f"{text}_file"
    if not text:
        text = DEFAULT_LOCALIZED_SLUG_FALLBACK
    if max_len <= 0:
        return text
    return text[:max_len]


def choose_timestamp(row: dict) -> dt.datetime:
    exif_dt = row.get("exif_datetime") or ""
    if exif_dt:
        try:
            parsed = dt.datetime.fromisoformat(exif_dt)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            return to_seattle(parsed)
    file_mtime = dt.datetime.fromisoformat(row["file_mtime"])
    if file_mtime.tzinfo is None:
        # file_mtime is produced from filesystem stat and should be treated as UTC
        # when legacy manifests carry naive ISO strings.
        file_mtime = file_mtime.replace(tzinfo=dt.timezone.utc)
    return to_seattle(file_mtime)


_CN_ALLOWED_RE = re.compile(r"[^\u4e00-\u9fff，。！？；：、（）《》“”‘’【】—…·]+")


def sanitize_cn_text(text: str, default_text: str) -> str:
    if not text:
        return default_text
    cleaned = _CN_ALLOWED_RE.sub("", text)
    cleaned = cleaned.strip()
    return cleaned if cleaned else default_text


def sanitize_cn_tags(tags: Sequence[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        val = sanitize_cn_text(str(tag).strip(), "")
        if val and val not in cleaned:
            cleaned.append(val)
    return cleaned


def safe_join(root: Path, *parts: str) -> Path:
    safe_parts = []
    for part in parts:
        part_text = _normalize_text_nfc(part).strip().replace("\\", "/")
        if Path(part_text).is_absolute():
            raise ValueError("unsafe absolute path detected")
        safe_parts.append(part_text)
    root_resolved = Path(_normalize_text_nfc(str(root.resolve())))
    candidate = Path(_normalize_text_nfc(str(root.joinpath(*safe_parts).resolve())))
    if root_resolved == candidate:
        return candidate
    if root_resolved not in candidate.parents:
        raise ValueError("unsafe path traversal detected")
    return candidate


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    parent = path.parent
    stem = path.stem
    suffix = path.suffix
    i = 2
    while True:
        candidate = parent / f"{stem}__{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1
