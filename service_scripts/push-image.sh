#!/usr/bin/env bash
# Build the production image and push it to this service's ECR repository: ./dev.sh push-image <dev|prod> <aws-account-id>
# Runs on the host and needs docker and the AWS CLI with credentials for that account in the usual AWS_* variables or profile.
source "$(dirname "$0")/../scripts/_lib.sh"

# Must match the tax-infra service module: repository <name>-<environment>, immutable tags.
SERVICE_NAME=tax-service
REGION="${AWS_REGION:-ca-central-1}"

env_name="${1:-}"
account_id="${2:-}"
if [[ "$env_name" != dev && "$env_name" != prod ]] || [[ ! "$account_id" =~ ^[0-9]{12}$ ]]; then
    echo "usage: ./dev.sh push-image <dev|prod> <12-digit aws account id>" >&2
    exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
    echo "refusing to push: the working tree has uncommitted changes, so the tag would not describe the image" >&2
    exit 1
fi

tag="$(git rev-parse --short=12 HEAD)"
registry="$account_id.dkr.ecr.$REGION.amazonaws.com"
repository="$registry/$SERVICE_NAME-$env_name"

# Tags are immutable in the repository, so an image already there is left alone.
if aws ecr describe-images --region "$REGION" --repository-name "$SERVICE_NAME-$env_name" \
    --image-ids "imageTag=$tag" >/dev/null 2>&1; then
    echo "image $tag is already in $SERVICE_NAME-$env_name; nothing to push"
    echo "image_tag = \"$tag\""
    exit 0
fi

# The password goes straight from the AWS CLI to docker: never printed, never on a command line.
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$registry"
# Lambda on x86_64 (the infra module's default architecture); provenance off so ECR gets a plain single image.
docker buildx build --platform linux/amd64 --target prod --provenance=false --push -t "$repository:$tag" .
echo "pushed $repository:$tag"
echo "image_tag = \"$tag\""
