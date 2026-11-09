#!/usr/bin/env bash
# ruff check + ruff format --check + lint-spec + layer rules (lint-imports, once app/ exists).
source "$(dirname "$0")/_lib.sh"
run_nodb sh -c "ruff check . && ruff format --check ."
"$(dirname "$0")/lint-spec.sh"
if [[ -d app ]]; then run_nodb lint-imports; fi
