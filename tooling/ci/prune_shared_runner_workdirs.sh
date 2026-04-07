#!/usr/bin/env bash
set -euo pipefail

DEFAULT_ROOT="$HOME/.cache/movi-shared-runners"

usage() {
  cat <<'EOF'
Usage:
  bash tooling/ci/prune_shared_runner_workdirs.sh [--dry-run] [--root <path>] [--max-runners N]

Clears only temp-shared-pool-*/_work/* when no Runner.Worker process is active.
Never removes runner installation/configuration layers such as:
  - bin
  - externals
  - _diag
  - .runner
  - .service
  - run.sh / runsvc.sh / svc.sh
  - base
  - actions-runner-*.tar.gz
EOF
}

dry_run=0
root="$DEFAULT_ROOT"
max_runners=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      dry_run=1
      ;;
    --root)
      shift
      root="${1:-}"
      if [ -z "$root" ]; then
        echo "❌ prune_shared_runner_workdirs: --root requires a path" >&2
        exit 2
      fi
      ;;
    --max-runners)
      shift
      max_runners="${1:-}"
      if ! [[ "$max_runners" =~ ^[0-9]+$ ]]; then
        echo "❌ prune_shared_runner_workdirs: --max-runners expects an integer" >&2
        exit 2
      fi
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "❌ prune_shared_runner_workdirs: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if ps aux | grep -F "Runner.Worker" | grep -v grep >/dev/null 2>&1; then
  echo "❌ prune_shared_runner_workdirs: active Runner.Worker process detected; refusing to clear shared runner workdirs" >&2
  exit 1
fi

python3 - "$root" "$dry_run" "$max_runners" <<'PY'
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
dry_run = sys.argv[2] == "1"
max_runners = int(sys.argv[3])


def _size_kib(path: Path) -> int:
    if not path.exists():
        return 0
    return int(subprocess.check_output(["du", "-sk", str(path)], text=True).split()[0])


work_roots = sorted(root.glob("temp-shared-pool-*/_work"))
if max_runners > 0:
    work_roots = work_roots[:max_runners]

total_kib = sum(_size_kib(path) for path in work_roots if path.exists())
action = "would prune" if dry_run else "pruned"
print(f"{action} shared runner workdirs total_kib={total_kib}")
for work in work_roots:
    print(f"- {work} size_kib={_size_kib(work)}")
    if dry_run or not work.exists():
        continue
    for child in list(work.iterdir()):
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)
PY
