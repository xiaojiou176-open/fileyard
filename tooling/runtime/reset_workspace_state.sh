#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="${MOVI_WORKSPACE_ROOT:-$HOME/.fileyard/workspaces/default}"
rm -rf "$WORKSPACE_ROOT/.movi"
mkdir -p "$WORKSPACE_ROOT/.movi"
printf 'reset workspace state\n'
