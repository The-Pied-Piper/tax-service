#!/usr/bin/env bash
# One-time scaffold of app/ and tests/ from openapi/openapi.yml [--name NAME] [--template-repo URL].
source "$(dirname "$0")/_lib.sh"

# --template-repo is recorded in TEMPLATE_REPO for ./dev.sh upgrade. Without it,
# the template is recorded at the same host and scheme as this repo's origin.
template=""
args=()
while (($#)); do
    case "$1" in
        --template-repo)
            [[ $# -ge 2 ]] || { echo "--template-repo needs a value" >&2; exit 1; }
            template="$2"; shift 2 ;;
        --template-repo=*) template="${1#*=}"; shift ;;
        *) args+=("$1"); shift ;;
    esac
done

# Default the name from the host directory; inside the container cwd is always /app.
template="${template:-$(template_repo_from_origin)}"
compose build app && gen init --name "$(basename "$PWD")" --template-repo "$template" "${args[@]}"
echo "$template" > TEMPLATE_REPO
echo "recorded the template address in TEMPLATE_REPO: $(cat TEMPLATE_REPO)"
