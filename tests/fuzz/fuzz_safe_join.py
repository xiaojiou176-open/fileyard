from __future__ import annotations

import sys
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from packages.domain.normalization import safe_join


ROOT = Path("/tmp/movi-organizer-fuzz-root")


def TestOneInput(data: bytes) -> None:
    provider = atheris.FuzzedDataProvider(data)
    part_count = provider.ConsumeIntInRange(0, 4)
    parts = [provider.ConsumeUnicodeNoSurrogates(32) for _ in range(part_count)]
    try:
        joined = safe_join(ROOT, *parts)
    except ValueError:
        return

    resolved_root = ROOT.resolve()
    assert joined == resolved_root or resolved_root in joined.parents


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
