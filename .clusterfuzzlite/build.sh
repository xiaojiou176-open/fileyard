#!/bin/bash
set -euo pipefail

cd "$SRC/fileman"
export PYTHONPATH="${PYTHONPATH:-$SRC/fileman}"

compile_python_fuzzer tests/fuzz/fuzz_safe_join.py
