#!/usr/bin/env bash
# Wipe the database volume and start over (down -v, then up).
source "$(dirname "$0")/_lib.sh"
compose down -v --remove-orphans
exec "$(dirname "$0")/up.sh" "$@"
