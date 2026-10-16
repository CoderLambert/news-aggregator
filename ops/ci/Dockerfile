# syntax=docker/dockerfile:1
# Ubuntu 24.04 with preinstalled tools; Docker daemon lives in the DinD sidecar.
FROM node:22-bookworm-slim AS nodejs
FROM docker:29-cli AS dockercli
FROM myoung34/github-runner:2.337.0-ubuntu-noble

USER root
ENV DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ci-browsers \
    CHROMIUM_EXECUTABLE=/usr/local/bin/ci-chromium

COPY --from=nodejs /usr/local/bin/node /usr/local/bin/node
COPY --from=nodejs /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins/ /usr/local/libexec/docker/cli-plugins/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 python3.12-venv python3-pip build-essential \
       curl ca-certificates git jq libnss3-tools \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && python3 -m venv /opt/ci-playwright \
    && /opt/ci-playwright/bin/python -m pip install --no-cache-dir 'playwright==1.62.0' \
    && /opt/ci-playwright/bin/python -m playwright install --with-deps chromium \
    && browser="$(find /opt/ci-browsers -type f -name chrome -perm /111 -print -quit)" \
    && test -n "$browser" \
    && ln -s "$browser" /usr/local/bin/ci-chromium \
    && install -d -m 0750 -o runner -g runner /runner/data /ci-work/_work \
    && install -d -m 0770 -o runner -g runner /ci-work/_work/.ci-tmp \
    && docker compose version && python3 --version && node --version && npm --version \
    && test "$(id -u runner)" = 1001 && test "$(id -g runner)" = 121

COPY --chmod=0755 ops/ci/runner-entrypoint.sh /opt/ci/runner-entrypoint.sh
