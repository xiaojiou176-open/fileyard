#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

DEFAULT_ASSETS = (
    "docs/assets/storefront/hero-fileman-overview.svg",
    "docs/assets/storefront/ten-second-tour-fileman.svg",
    "docs/assets/storefront/before-after-fileman.svg",
    "docs/assets/storefront/social-preview-fileman.svg",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render outward-facing storefront SVGs to PNG for local/manual QA.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--asset", action="append", default=[])
    parser.add_argument("--out-dir", default="")
    return parser.parse_args()


def render_with_sips(asset: Path, out_path: Path) -> None:
    proc = subprocess.run(
        ["sips", "-s", "format", "png", str(asset), "--out", str(out_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"failed to render {asset}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")


def main() -> int:
    args = parse_args()
    repo_root = Path(args.root).resolve()
    assets = [repo_root / item for item in (args.asset or DEFAULT_ASSETS)]

    if args.out_dir:
        out_dir = Path(args.out_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(tempfile.mkdtemp(prefix="fileman-storefront-assets-"))

    print(f"render_root={out_dir}")
    for asset in assets:
        if not asset.is_file():
            raise SystemExit(f"missing asset: {asset.relative_to(repo_root)}")
        out_path = out_dir / f"{asset.stem}.png"
        render_with_sips(asset, out_path)
        print(f"{asset.relative_to(repo_root)} -> {out_path}")

    print("manual review checklist:")
    print("- title text is fully visible")
    print("- body copy does not overflow its card")
    print("- code or sample rows are not clipped at the bottom edge")
    print("- small labels stay readable after resize")
    print("note: external multimodal review stays local/manual and out of required CI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
