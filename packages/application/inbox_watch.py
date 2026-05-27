from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from packages.infrastructure.watch_source_store import WatchSource


@dataclass(frozen=True)
class InboxBatch:
    id: str
    watch_source_id: str
    source_name: str
    input_root: str
    file_count: int
    file_paths: tuple[str, ...]
    strategy_pack_id: str = ""
    analyze_job_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "watch_source_id": self.watch_source_id,
            "source_name": self.source_name,
            "input_root": self.input_root,
            "file_count": self.file_count,
            "file_paths": list(self.file_paths),
            "strategy_pack_id": self.strategy_pack_id,
            "analyze_job_id": self.analyze_job_id,
        }


def scan_watch_sources_once(sources: Iterable[WatchSource]) -> List[InboxBatch]:
    batches: List[InboxBatch] = []
    for source in sources:
        if not source.enabled:
            continue
        input_root = Path(source.input_root).expanduser()
        if not input_root.exists() or not input_root.is_dir():
            continue
        file_paths = sorted(str(path.resolve()) for path in input_root.iterdir() if path.is_file())
        if not file_paths:
            continue
        batch_id = hashlib.sha256(f"{source.id}:{source.input_root}:{len(file_paths)}".encode("utf-8")).hexdigest()[:12]
        batches.append(
            InboxBatch(
                id=batch_id,
                watch_source_id=source.id,
                source_name=source.name,
                input_root=str(input_root.resolve()),
                file_count=len(file_paths),
                file_paths=tuple(file_paths),
                strategy_pack_id=source.strategy_pack_id,
            )
        )
    return batches
