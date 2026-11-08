#!/usr/bin/env bash
# Entry point for all local workflows: ./dev.sh <command> [args]  ->  scripts/<command>.sh
set -euo pipefail
cd "$(dirname "$0")"
cmd="${1:-help}"; shift || true
if [[ "$cmd" == _* || ! -x "scripts/$cmd.sh" ]]; then
    echo "unknown command: $cmd" >&2
    exec scripts/help.sh >&2
fi
exec "scripts/$cmd.sh" "$@"
