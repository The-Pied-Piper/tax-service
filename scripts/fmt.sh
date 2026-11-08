#!/usr/bin/env bash
# ruff format + ruff check --fix.
source "$(dirname "$0")/_lib.sh"
run_nodb sh -c "ruff format . && ruff check --fix ."
