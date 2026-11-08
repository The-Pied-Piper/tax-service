#!/usr/bin/env bash
# Apply migrations to the dev db, then fail if ORM models have drifted from them.
source "$(dirname "$0")/_lib.sh"
[[ -d app ]] || { echo "no app/ yet; skipping migration check"; exit 0; }
run sh -c "alembic upgrade head && alembic check"
