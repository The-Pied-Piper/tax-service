#!/usr/bin/env bash
# Fail if app/generated/ is out of date with openapi/openapi.yml (runs sync, diffs).
source "$(dirname "$0")/_lib.sh"
[[ -d app ]] || { echo "no app/ yet; skipping generated-code check"; exit 0; }
gen sync >/dev/null
if [[ -n "$(git status --porcelain -- app/generated)" ]]; then
    echo "app/generated is stale; commit the result of ./dev.sh sync:" >&2
    git --no-pager status --short -- app/generated >&2
    exit 1
fi
echo "app/generated is up to date"
