#!/usr/bin/env bash
# Entry point for all local workflows: ./dev.sh <command> [args]
# Runs scripts/<command>.sh (template-owned), else service_scripts/<command>.sh (service-owned).
set -euo pipefail
cd "$(dirname "$0")"
cmd="${1:-help}"; shift || true
if [[ "$cmd" == _* ]]; then
    echo "unknown command: $cmd" >&2
    exec scripts/help.sh >&2
elif [[ -x "scripts/$cmd.sh" ]]; then
    exec "scripts/$cmd.sh" "$@"
elif [[ -x "service_scripts/$cmd.sh" ]]; then
    exec "service_scripts/$cmd.sh" "$@"
fi
echo "unknown command: $cmd" >&2
exec scripts/help.sh >&2
