#!/usr/bin/env bash
# Stop and remove containers (-v also drops the database volume).
source "$(dirname "$0")/_lib.sh"
compose down "$@"
