#!/bin/bash
set -euo pipefail

cd "$SRC/fileyard"
export PYTHONPATH="${PYTHONPATH:-$SRC/fileyard}"

compile_python_fuzzer tests/fuzz/fuzz_safe_join.py
