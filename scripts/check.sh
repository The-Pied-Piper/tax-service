#!/usr/bin/env bash
# check-generated + lint + typecheck + test + check-migrations (what CI runs).
source "$(dirname "$0")/_lib.sh"
s="$(dirname "$0")"
"$s/check-generated.sh" && "$s/lint.sh" && "$s/typecheck.sh" && "$s/test.sh" && "$s/check-migrations.sh"
