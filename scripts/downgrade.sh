#!/usr/bin/env bash
# alembic downgrade -1.
source "$(dirname "$0")/_lib.sh"
run alembic downgrade -1
