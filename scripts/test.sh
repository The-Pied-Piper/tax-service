#!/usr/bin/env bash
# pytest [args].
source "$(dirname "$0")/_lib.sh"
run pytest "$@"
