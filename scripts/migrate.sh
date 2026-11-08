#!/usr/bin/env bash
# alembic upgrade head.
source "$(dirname "$0")/_lib.sh"
run alembic upgrade head
