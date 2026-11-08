#!/usr/bin/env bash
# List commands (this text comes from line 2 of each script).
cd "$(dirname "$0")/.."
# Lines for the runnable commands in one folder (what dev.sh would run: executable files).
list() {
    local f name
    for f in "$1"/*.sh; do
        [[ -f "$f" && -x "$f" ]] || continue
        name="$(basename "${f%.sh}")"
        [[ "$name" == _* ]] && continue
        # scripts/ wins, so a service script with the same name never runs.
        [[ "$1" != service_scripts || ! -x "scripts/$name.sh" ]] || continue
        printf "  %-17s %s\n" "$name" "$(sed -n '2s/^# *//p' "$f")"
    done
}
echo "usage: ./dev.sh <command> [args]"
echo
list scripts
own="$(list service_scripts)"
if [[ -n "$own" ]]; then
    echo
    echo "this service's own commands (service_scripts/):"
    echo "$own"
fi
