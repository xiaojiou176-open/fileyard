# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import uvicorn


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Fileorganize Web API server.")
    parser.add_argument(
        "--host",
        default=os.environ.get("FILEORGANIZE_WEB_API_HOST", "127.0.0.1"),
        help="Host interface to bind (default: FILEORGANIZE_WEB_API_HOST or 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("FILEORGANIZE_WEB_API_PORT", "18080")),
        help="TCP port to bind (default: FILEORGANIZE_WEB_API_PORT or 18080).",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        help="Uvicorn log level (default: info).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    uvicorn.run(
        "apps.api.web_api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
