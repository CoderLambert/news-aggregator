#!/bin/sh
set -eu
# Never print a token, inherit xtrace, accept user credentials, or load arbitrary
# environment/config paths. This only bridges the upstream env configuration.
set +x
token_file=/run/secrets/rsshub_github_token
if [ ! -f "$token_file" ] || [ ! -r "$token_file" ]; then
    printf 'rsshub: service token file unavailable\n' >&2
    exit 78
fi
GITHUB_ACCESS_TOKEN=$(cat "$token_file")
case "$GITHUB_ACCESS_TOKEN" in
    ''|*[!A-Za-z0-9_]*) printf 'rsshub: invalid service token format\n' >&2; exit 78 ;;
esac
if [ "${#GITHUB_ACCESS_TOKEN}" -gt 512 ]; then
    printf 'rsshub: service token exceeds limit\n' >&2
    exit 78
fi
export GITHUB_ACCESS_TOKEN
exec "$@"
