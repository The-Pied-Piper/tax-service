#!/usr/bin/env bash
# Build the production image and push it to this service's ECR repository: ./dev.sh push-image <dev|prod> <aws-account-id> [release-tag]
# The image is tagged sha-<12-character commit id>. With a release tag (for example v1) the same image also gets that tag.
# Runs on the host and needs docker and the AWS CLI with credentials for that account in the usual AWS_* variables or profile.
source "$(dirname "$0")/../scripts/_lib.sh"
# (_lib.sh sets -euo pipefail: pipefail is what makes the login pipe below safe.)

# Must match the tax-infra service module: repository <name>-<environment>, immutable tags.
SERVICE_NAME=tax-service
REGION="${AWS_REGION:-ca-central-1}"

env_name="${1:-}"
account_id="${2:-}"
release_tag="${3:-}"
if [[ "$env_name" != dev && "$env_name" != prod ]] || [[ ! "$account_id" =~ ^[0-9]{12}$ ]] || [[ $# -gt 3 ]]; then
    echo "usage: ./dev.sh push-image <dev|prod> <12-digit aws account id> [release tag such as v1]" >&2
    exit 2
fi
# tax-infra keeps release tags (prefix v) forever and expires build tags (prefix sha-) after the newest 30.
if [[ -n "$release_tag" && ! "$release_tag" =~ ^v[0-9][0-9A-Za-z._-]{0,126}$ ]]; then
    echo "a release tag must be v and a number, then only letters, digits, dot, dash and underscore: $release_tag" >&2
    exit 2
fi
# The region ends up in the host name that receives the ECR password.
if [[ ! "$REGION" =~ ^[a-z]{2}(-[a-z]+)+-[0-9]$ ]]; then
    echo "AWS_REGION does not look like an AWS region: $REGION" >&2
    exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
    echo "refusing to push: the working tree has uncommitted changes, so the tag would not describe the image" >&2
    exit 1
fi

# The build tag names the commit (not a content hash); tax-infra expires old sha- tags.
tag="sha-$(git rev-parse --short=12 HEAD)"
registry="$account_id.dkr.ecr.$REGION.amazonaws.com"
repository_name="$SERVICE_NAME-$env_name"

digest=""
# Adds the release tag to the image that already carries the build tag.
# Tags are immutable, so a release tag that exists must already point at this image.
# Reads the digest of the image that carries the build tag; stops unless it is a real digest.
read_digest() {
    digest="$(aws ecr describe-images --region "$REGION" --repository-name "$repository_name" \
        --image-ids "imageTag=$tag" --query 'imageDetails[0].imageDigest' --output text)"
    if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
        echo "unexpected digest for $tag: $digest" >&2
        exit 1
    fi
}
add_release_tag() {
    [[ -n "$release_tag" ]] || return 0
    local existing manifest
    if existing="$(aws ecr describe-images --region "$REGION" --repository-name "$repository_name" \
        --image-ids "imageTag=$release_tag" --query 'imageDetails[0].imageDigest' --output text 2>&1)"; then
        if [[ "$existing" == "$digest" ]]; then
            echo "image $tag already has release tag $release_tag"
            return 0
        fi
        echo "release tag $release_tag already points at a different image ($existing); choose a new one" >&2
        return 1
    elif [[ "$existing" != *ImageNotFoundException* ]]; then
        echo "could not check $repository_name for release tag $release_tag: $existing" >&2
        return 1
    fi
    manifest="$(aws ecr batch-get-image --region "$REGION" --repository-name "$repository_name" \
        --image-ids "imageTag=$tag" --query 'images[0].imageManifest' --output text)"
    if [[ -z "$manifest" || "$manifest" == None ]]; then
        echo "could not read the manifest of $tag" >&2
        return 1
    fi
    # The digest makes ECR refuse a manifest that is not exactly this image.
    aws ecr put-image --region "$REGION" --repository-name "$repository_name" \
        --image-tag "$release_tag" --image-manifest "$manifest" --image-digest "$digest" >/dev/null
    echo "added release tag $release_tag to $tag ($digest)"
}
print_result() {
    # The digest lets the operator record exactly which image the tag names.
    echo "digest = \"$digest\""
    echo "image_tag = \"${release_tag:-$tag}\""
}

# Only "not found" means absent; any other error (credentials, region, no repository) stops here.
if found="$(aws ecr describe-images --region "$REGION" --repository-name "$repository_name" \
    --image-ids "imageTag=$tag" 2>&1)"; then
    echo "image $tag is already in $repository_name (pushed earlier, not by this run); nothing to push"
    read_digest
    add_release_tag
    print_result
    exit 0
elif [[ "$found" != *ImageNotFoundException* ]]; then
    echo "could not check $repository_name for image $tag: $found" >&2
    exit 1
fi

# The password goes straight from the AWS CLI to docker: never printed, never on a command line.
# Log out afterwards so the 12-hour token does not stay in the Docker credential store
# (this also drops any earlier login to the same registry).
trap 'docker logout "$registry" >/dev/null 2>&1 || true' EXIT
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$registry"
# Build from the committed files only (git archive), so an ignored local file cannot end up in the image.
# Lambda on x86_64 (the infra module's default architecture); provenance off so ECR gets a plain single image.
git archive HEAD | docker buildx build --platform linux/amd64 --target prod --provenance=false --push \
    -t "$registry/$repository_name:$tag" -
echo "pushed $registry/$repository_name:$tag"
read_digest
add_release_tag
print_result
