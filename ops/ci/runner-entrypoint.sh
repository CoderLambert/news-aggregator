#!/usr/bin/env bash
set -Eeuo pipefail

# Registration token is read from a short-lived local bind file only if no
# persisted GitHub runner identity exists. Never put it in Compose environment.
if [[ ! -s /runner/data/.runner ]]; then
    if [[ ! -s /run/ci-registration-token ]]; then
        echo "Runner is not registered: run bash ops/ci/manage.sh install." >&2
        exit 2
    fi
    export RUNNER_TOKEN
    RUNNER_TOKEN="$(cat /run/ci-registration-token)"
fi

exec /entrypoint.sh "$@"
