#!/usr/bin/env bash
# Shared helpers; sourced by every script. Not a command.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Run as the host user so files written through the bind mount stay yours.
export UID GID="$(id -g)"

# Host conveniences for the app container. Your git identity is passed through
# (compose.yaml names the variables). compose.yaml mounts the ssh agent socket
# named by SSH_AGENT_SOCKET, else an empty placeholder. We pick the socket the
# container engine can see: Docker Desktop (macOS, or a desktop-* context)
# exposes the host agent at a fixed path inside its VM (untested here); a native
# engine can mount $SSH_AUTH_SOCK itself. DEV_SSH_AGENT=0 turns the sharing off.
git_identity() { git config "user.$1" 2>/dev/null || true; }
name="$(git_identity name)"; email="$(git_identity email)"
if [[ -n "$name" ]]; then
    export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-$name}" GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$name}"
fi
if [[ -n "$email" ]]; then
    export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-$email}" GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-$email}"
fi
unset name email
if [[ -z "${SSH_AGENT_SOCKET:-}" ]]; then
    agent_socket=
    if [[ "${DEV_SSH_AGENT:-1}" != 0 && "${IN_APP_CONTAINER:-}" != 1 ]]; then
        if [[ "$(uname -s)" == Darwin || "$(docker context show 2>/dev/null || true)" == desktop-* ]]; then
            agent_socket=/run/host-services/ssh-auth.sock
        elif [[ -S "${SSH_AUTH_SOCK:-}" ]]; then
            agent_socket="$SSH_AUTH_SOCK"
        fi
    fi
    export SSH_AGENT_SOCKET="${agent_socket:-/dev/null}"
    unset agent_socket
fi

# compose.yaml sets IN_APP_CONTAINER=1 on the app service. Inside it (e.g. a VS
# Code dev container) commands run directly; from the host they run in a
# one-off app container. Either way, `./dev.sh test` does the same thing.
in_app_container() { [[ "${IN_APP_CONTAINER:-}" == 1 ]]; }

# Managing containers only works from the host.
compose() {
    if in_app_container; then
        echo "this command manages containers: run it from the host, not inside the app container" >&2
        exit 1
    fi
    docker compose "$@"
}
# A command in the app environment (with the database available).
run() {
    if in_app_container; then "$@"; else compose run --rm app "$@"; fi
}
# A command in the app environment, without starting the database.
run_nodb() {
    if in_app_container; then "$@"; else compose run --rm --no-deps app "$@"; fi
}
# The generator, from the copy vendored in this repo.
gen() { run_nodb python -m tools.service_gen.cli "$@"; }

# Where the template lives on its host, as OWNER/REPO.git: $TEMPLATE_PATH if
# set, else the first line of the TEMPLATE_HOME file. This is the one place a
# copy of the template names its own home; change that file when you copy it.
TEMPLATE_PATH="${TEMPLATE_PATH:-$(head -n 1 TEMPLATE_HOME 2>/dev/null | tr -d '\r' || true)}"

# The template at the same host and scheme (SSH or HTTPS) as this repo's own
# origin, so access that works for the service works for the template.
template_repo_from_origin() {
    local origin rest
    [[ -n "$TEMPLATE_PATH" ]] || {
        echo "the template's address is unknown: set TEMPLATE_REPO, TEMPLATE_PATH or the TEMPLATE_HOME file" >&2
        exit 1
    }
    origin="$(git remote get-url origin 2>/dev/null)" || origin=""
    case "$origin" in
        git@*:*) echo "${origin%%:*}:$TEMPLATE_PATH" ;;
        ssh://*) rest="${origin#ssh://}"; echo "ssh://${rest%%/*}/$TEMPLATE_PATH" ;;
        https://*) rest="${origin#https://}"; echo "https://${rest%%/*}/$TEMPLATE_PATH" ;;
        *) echo "https://github.com/$TEMPLATE_PATH" ;;
    esac
}

# Where to fetch the template: $TEMPLATE_REPO if set, else the address init
# recorded in the TEMPLATE_REPO file.
template_repo() {
    local recorded=""
    [[ -f TEMPLATE_REPO ]] && recorded="$(head -n 1 TEMPLATE_REPO | tr -d '\r')"
    if [[ -n "${TEMPLATE_REPO:-}" ]]; then
        echo "$TEMPLATE_REPO"
    elif [[ -n "$recorded" ]]; then
        echo "$recorded"
    else
        echo "the template's address is unknown: set TEMPLATE_REPO or run ./dev.sh init" >&2
        exit 1
    fi
}
