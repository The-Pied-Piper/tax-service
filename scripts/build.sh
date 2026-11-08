#!/usr/bin/env bash
# Rebuild the dev image (after changing requirements*.in (recompile the .txt files first; see the header of requirements.txt)).
source "$(dirname "$0")/_lib.sh"
compose build app "$@"
