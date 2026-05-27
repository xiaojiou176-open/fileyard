#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="${FILEMAN_WORKSPACE_ROOT:-$HOME/.fileman/workspaces/default}"
rm -rf "$WORKSPACE_ROOT/.fileman"
mkdir -p "$WORKSPACE_ROOT/.fileman"
printf 'reset workspace state\n'
