from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


@dataclass(frozen=True)
class CollectionSummary:
    id: str
    title: str
    reason: str
    confidence: float
    row_ids: tuple[str, ...]
    kind: str = ""
    next_step: str = ""
    capture_day: str = ""
    batch_hint: str = ""
    source_root: str = ""
    dominant_media_type: str = ""
    media_types: tuple[str, ...] = ()
    explainability: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "reason": self.reason,
            "confidence": self.confidence,
            "row_ids": list(self.row_ids),
            "kind": self.kind,
            "next_step": self.next_step,
            "capture_day": self.capture_day,
            "batch_hint": self.batch_hint,
            "source_root": self.source_root,
            "dominant_media_type": self.dominant_media_type,
            "media_types": list(self.media_types),
            "explainability": list(self.explainability),
        }


def apply_collection_intelligence(rows: Iterable[Mapping[str, Any]]) -> tuple[List[Dict[str, Any]], List[CollectionSummary]]:
    enriched: List[Dict[str, Any]] = []
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        payload = dict(row)
        signal = _collection_signal(payload)
        collection_id = _collection_id(signal["group_key"])
        payload["collection_id"] = collection_id
        payload["collection_title"] = signal["title"]
        payload["collection_reason"] = signal["reason"]
        payload["collection_confidence"] = signal["confidence"]
        payload["collection_capture_day"] = signal["capture_day"]
        payload["collection_batch_hint"] = signal["batch_hint"]
        payload["collection_source_root"] = signal["source_root"]
        payload["collection_kind"] = signal["kind"]
        payload["collection_next_step"] = signal["next_step"]
        payload["collection_explainability"] = list(signal["explainability"])
        enriched.append(payload)
        grouped.setdefault(collection_id, []).append(payload)

    collections: List[CollectionSummary] = []
    for collection_id, members in grouped.items():
        first = members[0]
        media_counter = Counter(str(item.get("media_type", "") or "unknown") for item in members)
        dominant_media_type = media_counter.most_common(1)[0][0] if media_counter else "unknown"
        collections.append(
            CollectionSummary(
                id=collection_id,
                title=str(first.get("collection_title", "") or "Collection"),
                reason=str(first.get("collection_reason", "") or "grouped by capture day + batch hint + source root"),
                confidence=float(first.get("collection_confidence", 0.0) or 0.0),
                row_ids=tuple(
                    str(item.get("id", item.get("row_id", "")) or "")
                    for item in members
                    if str(item.get("id", item.get("row_id", "")) or "")
                ),
                kind=str(first.get("collection_kind", "") or "capture_batch"),
                next_step=str(
                    first.get("collection_next_step", "") or _collection_next_step(str(first.get("collection_kind", "") or "capture_batch"))
                ),
                capture_day=str(first.get("collection_capture_day", "") or ""),
                batch_hint=str(first.get("collection_batch_hint", "") or ""),
                source_root=str(first.get("collection_source_root", "") or ""),
                dominant_media_type=dominant_media_type,
                media_types=tuple(sorted(media_counter)),
                explainability=tuple(str(item) for item in first.get("collection_explainability", []) if str(item).strip()),
            )
        )
    collections.sort(key=lambda item: (item.capture_day or "undated", item.title, item.id))
    return enriched, collections


def _collection_signal(row: Mapping[str, Any]) -> Dict[str, Any]:
    metadata = row.get("metadata", {})
    meta = metadata if isinstance(metadata, dict) else {}
    original_path = str(row.get("original_path", row.get("path", "")) or "")
    path = Path(original_path)
    source_root = path.parent.name or "root-batch"
    capture_day = str(meta.get("exif_datetime", "") or meta.get("file_mtime", "") or "")[:10] or "undated"
    batch_hint = _batch_hint(path, meta, fallback=source_root)
    explainability = (
        f"capture_day:{capture_day}",
        f"batch_hint:{batch_hint}",
        f"source_root:{source_root}",
    )
    confidence = 0.92 if capture_day != "undated" and batch_hint != source_root else 0.84 if capture_day != "undated" else 0.72
    return {
        "group_key": f"{capture_day}:{source_root}",
        "title": f"{capture_day if capture_day != 'undated' else source_root} / {source_root}",
        "reason": "grouped by capture day + source root, with batch hint kept as an explanation signal",
        "confidence": confidence,
        "capture_day": capture_day,
        "batch_hint": batch_hint,
        "source_root": source_root,
        "kind": _collection_kind(source_root, batch_hint),
        "next_step": _collection_next_step(_collection_kind(source_root, batch_hint)),
        "explainability": explainability,
    }


def _batch_hint(path: Path, metadata: Mapping[str, Any], *, fallback: str) -> str:
    for key in ("collection_hint", "collection", "album", "event", "batch_label"):
        raw = str(metadata.get(key, "") or "").strip()
        if raw:
            return raw
    stem = path.stem.strip()
    if not stem:
        return fallback
    normalized = stem.rstrip("0123456789").rstrip("_- ")
    normalized = re.sub(r"\b(img|image|photo|screenshot|dsc|pxl|mvimg)\b", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[_\-\s]+", " ", normalized).strip()
    if len(normalized) >= 3:
        return normalized.lower()
    return fallback


def _collection_id(group_key: str) -> str:
    return hashlib.sha256(group_key.encode("utf-8")).hexdigest()[:12]


def _collection_kind(source_root: str, batch_hint: str) -> str:
    signal = f"{source_root} {batch_hint}".lower()
    if any(token in signal for token in ("travel", "trip", "ticket", "hotel", "boarding", "旅行")):
        return "travel_batch"
    if any(token in signal for token in ("receipt", "invoice", "bill", "发票", "收据")):
        return "receipt_run"
    if any(token in signal for token in ("meeting", "notes", "slides", "录音", "会议")):
        return "meeting_bundle"
    if any(token in signal for token in ("chat", "message", "wechat", "聊天")):
        return "chat_export"
    return "capture_batch"


def _collection_next_step(kind: str) -> str:
    if kind == "travel_batch":
        return "Review this trip batch together, then promote repeated edits into a draft rule if the pattern holds."
    if kind == "receipt_run":
        return "Review this receipt run together and batch-assign the final category before apply dry-run."
    if kind == "meeting_bundle":
        return "Confirm the shared meeting context before batch triage or naming changes."
    if kind == "chat_export":
        return "Review this export bundle as one batch before deciding ignore or naming actions."
    return "Review this batch together before moving toward Apply."
