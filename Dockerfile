# syntax=docker/dockerfile:1
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
# git: requirements.txt installs tax-engine from its repository.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
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
COPY openapi ./openapi
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
# AWS Lambda Web Adapter: on Lambda it forwards each request to uvicorn on 8080;
# anywhere else the file is never run, so this is the same image as before.
# The infra module sets AWS_LWA_PORT and the readiness path (/status/readyz).
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter
USER app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
