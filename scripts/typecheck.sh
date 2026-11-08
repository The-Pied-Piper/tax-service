#!/usr/bin/env bash
# mypy over the whole repo (only tools/ before init has run).
source "$(dirname "$0")/_lib.sh"
targets=(tools)
[[ -d app ]] && targets=(.)
run_nodb mypy "${targets[@]}"
