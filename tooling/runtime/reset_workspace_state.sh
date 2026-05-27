#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="${FILEORGANIZE_WORKSPACE_ROOT:-$HOME/.fileorganize/workspaces/default}"
rm -rf "$WORKSPACE_ROOT/.fileorganize"
mkdir -p "$WORKSPACE_ROOT/.fileorganize"
printf 'reset workspace state\n'
