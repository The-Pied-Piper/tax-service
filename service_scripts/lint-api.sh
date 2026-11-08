#!/usr/bin/env bash
# Lint openapi/openapi.yml with Spectral and the AEP rules (needs Node 20+; runs on the host).
source "$(dirname "$0")/../scripts/_lib.sh"
npm ci --no-audit --no-fund --loglevel=error
exec npx --no-install spectral lint openapi/openapi.yml "$@"
