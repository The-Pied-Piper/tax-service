#!/usr/bin/env bash
# Validate openapi/openapi.yml against the OpenAPI 3 schema.
source "$(dirname "$0")/_lib.sh"
run_nodb python -m openapi_spec_validator openapi/openapi.yml
