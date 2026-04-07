#!/usr/bin/env bash
set -euo pipefail

# Gate helper for CI / pre-push image-contract reuse: prefer tag refs for stable pull visibility.

if [ "$#" -ne 1 ]; then
  echo "Usage: bash tooling/ci/read_ci_contract_image_ref.sh <digest-contract-path>" >&2
  exit 2
fi

digest_path="$1"
tag_path="${digest_path%.txt}.tag.txt"

if [ -f "$tag_path" ]; then
  cat "$tag_path"
  exit 0
fi

cat "$digest_path"
