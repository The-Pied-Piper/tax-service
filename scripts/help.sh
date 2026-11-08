#!/usr/bin/env bash
# List commands (this text comes from line 2 of each scripts/*.sh).
cd "$(dirname "$0")"
echo "usage: ./dev.sh <command> [args]"
echo
for f in *.sh; do
    name="${f%.sh}"
    [[ "$name" == _* ]] && continue
    printf "  %-17s %s\n" "$name" "$(sed -n '2s/^# *//p' "$f")"
done
