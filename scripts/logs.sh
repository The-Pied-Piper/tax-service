#!/usr/bin/env bash
# Follow app logs.
source "$(dirname "$0")/_lib.sh"
compose logs -f app "$@"
