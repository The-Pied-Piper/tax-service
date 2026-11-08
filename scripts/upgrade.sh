#!/usr/bin/env bash
# Pull template-owned files (dev.sh, scripts/, tools/service_gen/, CI workflow) from the template [REF], then sync.
source "$(dirname "$0")/_lib.sh"

repo="$(template_repo)"
ref="${1:-main}"
owned=(dev.sh scripts tools/service_gen .github/workflows/ci.yml)

if [[ -n "$(git status --porcelain -- "${owned[@]}")" ]]; then
    echo "uncommitted changes in ${owned[*]}; commit or stash them first" >&2
    exit 1
fi

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
echo ">> fetching $repo @ $ref"
git clone -q --depth 1 --branch "$ref" "$repo" "$tmp"
sha="$(git -C "$tmp" rev-parse --short HEAD)"
for path in "${owned[@]}"; do
    [[ -e "$tmp/$path" ]] || { echo "$repo@$ref has no $path; aborting" >&2; exit 1; }
done

for path in "${owned[@]}"; do
    rm -rf "$path"
    mkdir -p "$(dirname "$path")"
    cp -R "$tmp/$path" "$path"
done
printf '%s %s %s\n' "$ref" "$sha" "$(date -u +%Y-%m-%d)" > TEMPLATE_VERSION
echo ">> now at $(cat TEMPLATE_VERSION)"

if in_app_container; then
    echo ">> inside the app container: skipping the image rebuild"
    echo "   (run ./dev.sh build from the host if requirements changed)"
else
    echo ">> rebuilding dev image"
    compose build app
fi
echo ">> re-syncing generated code"
gen sync
echo
echo "Review with: git status && git diff"
