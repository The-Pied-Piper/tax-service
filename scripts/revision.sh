#!/usr/bin/env bash
# alembic revision --autogenerate -m "MESSAGE".
source "$(dirname "$0")/_lib.sh"
[[ $# -ge 1 ]] || { echo "usage: ./dev.sh revision MESSAGE" >&2; exit 2; }
run alembic revision --autogenerate -m "$*"
