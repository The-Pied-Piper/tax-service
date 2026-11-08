#!/usr/bin/env bash
# Regenerate app/generated/ and add stubs after editing openapi/openapi.yml.
source "$(dirname "$0")/_lib.sh"
gen sync "$@"
