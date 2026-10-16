# syntax=docker/dockerfile:1
# Reusable G1 HTTP/Playwright/SSE sidecar, without host Docker credentials.
# The invoking smoke runner attaches it to the gateway's network namespace.
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ci-browsers \
    CHROMIUM_EXECUTABLE=/usr/local/bin/ci-chromium \
    HOME=/tmp

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libnss3-tools \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir 'playwright==1.62.0' \
    && python -m playwright install --with-deps chromium \
    && browser="$(find /opt/ci-browsers -type f -name chrome -perm /111 -print -quit)" \
    && test -n "$browser" \
    && ln -s "$browser" /usr/local/bin/ci-chromium \
    && (getent group 121 >/dev/null || groupadd --gid 121 ci-probe) \
    && useradd --uid 1001 --gid 121 --no-create-home --home-dir /tmp \
       --shell /usr/sbin/nologin ci-probe \
    && test "$(python -c 'import importlib.metadata; print(importlib.metadata.version("playwright"))')" = 1.62.0

WORKDIR /opt/newshub-smoke
COPY scripts/deploy/local_domain_acceptance.py scripts/deploy/local_domain_fixtures.py ./

USER 1001:121
CMD ["python", "/opt/newshub-smoke/local_domain_acceptance.py"]
