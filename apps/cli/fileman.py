#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Media pipeline entry.

Design goals:
- Prefer raw images for Gemini native API.
- Switch to Files API when inline payload is too large.
- Deterministic rename/move based on manifest.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Hard-cut entrypoint: execute from the current repo-root layout only.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    from apps.cli.cli_app import main

    main()


if __name__ == "__main__":
    main()
