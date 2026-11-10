#!/usr/bin/env bash
# Build the production image and push it to this service's ECR repository: ./dev.sh push-image <dev|prod> <aws-account-id>
# Runs on the host and needs docker and the AWS CLI with credentials for that account in the usual AWS_* variables or profile.
source "$(dirname "$0")/../scripts/_lib.sh"
# (_lib.sh sets -euo pipefail: pipefail is what makes the login pipe below safe.)

# Must match the tax-infra service module: repository <name>-<environment>, immutable tags.
SERVICE_NAME=tax-service
REGION="${AWS_REGION:-ca-central-1}"

env_name="${1:-}"
account_id="${2:-}"
if [[ "$env_name" != dev && "$env_name" != prod ]] || [[ ! "$account_id" =~ ^[0-9]{12}$ ]]; then
    echo "usage: ./dev.sh push-image <dev|prod> <12-digit aws account id>" >&2
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

# The tag names the commit (not a content hash).
tag="$(git rev-parse --short=12 HEAD)"
registry="$account_id.dkr.ecr.$REGION.amazonaws.com"
repository_name="$SERVICE_NAME-$env_name"

# Tags are immutable in the repository, so an image already there is left alone.
# Only "not found" means absent; any other error (credentials, region, no repository) stops here.
if found="$(aws ecr describe-images --region "$REGION" --repository-name "$repository_name" \
    --image-ids "imageTag=$tag" 2>&1)"; then
    echo "image $tag is already in $repository_name; nothing to push"
    echo "image_tag = \"$tag\""
    exit 0
elif [[ "$found" != *ImageNotFoundException* ]]; then
    echo "could not check $repository_name for image $tag: $found" >&2
    exit 1
fi

# The password goes straight from the AWS CLI to docker: never printed, never on a command line.
# Log out afterwards so the 12-hour token does not stay in the Docker credential store.
trap 'docker logout "$registry" >/dev/null 2>&1 || true' EXIT
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$registry"
# Build from the committed files only (git archive), so an ignored local file cannot end up in the image.
# Lambda on x86_64 (the infra module's default architecture); provenance off so ECR gets a plain single image.
git archive HEAD | docker buildx build --platform linux/amd64 --target prod --provenance=false --push \
    -t "$registry/$repository_name:$tag" -
echo "pushed $registry/$repository_name:$tag"
echo "image_tag = \"$tag\""
