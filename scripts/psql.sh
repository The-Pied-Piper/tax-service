#!/usr/bin/env bash
# psql against the dev database.
source "$(dirname "$0")/_lib.sh"
compose exec db psql -U app -d app "$@"
