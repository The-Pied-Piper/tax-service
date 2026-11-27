# syntax=docker/dockerfile:1
# The base image is pinned by digest on its own FROM line, so Dependabot keeps bumping it.
# CI sets PYTHON_IMAGE to a plain tag (python:3.13-slim and so on) to run the checks on other
# Python versions; those images are never shipped. The default names the pinned stage below.
ARG PYTHON_IMAGE=base-default
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS base-default
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./

# --- dev: runtime + tooling + generator deps; source is bind-mounted by compose --
FROM base AS dev
# Everyday tools for working inside the container (python:slim ships none of them).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gh git iputils-ping jq less make openssh-client postgresql-client procps unzip vim-tiny wget zip \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-dev.txt
# compose runs the container as your host uid:gid; give that pair a name, because
# ssh refuses to run as a uid with no /etc/passwd entry. HOME is /tmp (see compose.yaml).
ARG UID=1000
ARG GID=1000
RUN groupadd -o -g "$GID" dev && useradd -o -u "$UID" -g "$GID" -d /tmp -M -s /bin/bash dev
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--reload"]

# --- prod: runtime deps only, source baked in, non-root -------------------------
FROM base AS prod
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
RUN useradd --system --no-create-home --shell /usr/sbin/nologin app
# AWS Lambda Web Adapter: on Lambda it forwards each request to uvicorn on 8080;
# anywhere else the file is never run, so this is the same image as before.
# Pinned by digest (a tag can be moved); it runs inside every invocation and sees every request.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1@sha256:46d6625e68cbbdd2efab4a20245977664513f13ffef47915b000d431adcea0b4 /lambda-adapter /opt/extensions/lambda-adapter
# The app serves readiness under the spec's /api/v1 prefix. The adapter's default path has
# no prefix, so wherever this image runs, a deployment that sets this variable itself must use this path too.
ENV AWS_LWA_READINESS_CHECK_PATH=/api/v1/status/readyz
COPY openapi ./openapi
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
USER app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
