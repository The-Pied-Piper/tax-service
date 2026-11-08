#!/usr/bin/env bash
# Print (and try to open) the Swagger UI URL of the running app.
source "$(dirname "$0")/_lib.sh"
[[ -f .env ]] && source .env
# Base path = path component of the first `servers[].url` in the spec.
base="$(sed -n 's#^ *- *url: *[^/]*//[^/]*\(/[^ ]*\).*#\1#p' openapi/openapi.yml | head -1)"
url="http://localhost:${APP_PORT:-8080}${base%/}/ui/"
echo "$url"
if command -v xdg-open >/dev/null; then xdg-open "$url" >/dev/null 2>&1 &
elif command -v open >/dev/null; then open "$url"
fi
