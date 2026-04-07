#!/bin/bash
set -euo pipefail

cd "$SRC/movi-organizer"
export PYTHONPATH="${PYTHONPATH:-$SRC/movi-organizer}"

compile_python_fuzzer tests/fuzz/fuzz_safe_join.py
