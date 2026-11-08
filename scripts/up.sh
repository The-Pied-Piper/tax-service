#!/usr/bin/env bash
# Build and start app + postgres (foreground, hot reload). Args go to compose up.
source "$(dirname "$0")/_lib.sh"
compose up --build "$@"
