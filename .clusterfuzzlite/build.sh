#!/bin/bash
set -euo pipefail

cd "$SRC/fileorganize"
export PYTHONPATH="${PYTHONPATH:-$SRC/fileorganize}"

compile_python_fuzzer tests/fuzz/fuzz_safe_join.py
