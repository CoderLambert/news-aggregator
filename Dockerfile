# syntax=docker/dockerfile:1
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS rss-sync
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    DJANGO_ENV=production \
    DJANGO_DEBUG=0 \
    NEWSHUB_RUNTIME_ROLE=rss_sync \
    HOME=/home/newshub
WORKDIR /app
COPY backend/requirements-rss.lock /app/backend/requirements-rss.lock
RUN pip install --no-cache-dir --only-binary=:all: -r /app/backend/requirements-rss.lock \
    && groupadd --gid 10001 newshub \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin newshub \
    && mkdir -p /var/lib/newshub/db /var/lib/newshub/rss-runtime \
    && chown -R 10001:10001 /var/lib/newshub /home/newshub
COPY backend/ /app/backend/
USER 10001:10001
CMD ["python", "/app/backend/manage.py", "rss_sync_worker"]

FROM node:22-bookworm-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    HF_HOME=/root/.cache/huggingface \
    HOME=/root
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
ARG TORCH_VERSION=2.14.1+cpu
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==${TORCH_VERSION}"
# Keep the large CPU wheel cached across ordinary requirements/source changes.
COPY backend/requirements.txt /app/backend/requirements.txt
ARG NEWSHUB_PYPI_INDEX=https://pypi.org/simple
RUN pip install --no-cache-dir -r /app/backend/requirements.txt --index-url "${NEWSHUB_PYPI_INDEX}"
COPY backend/ /app/backend/
COPY start_waitress.py /app/start_waitress.py
COPY scripts/docker-migrate.py /app/scripts/docker-migrate.py
COPY --chmod=755 scripts/docker-entrypoint.sh /app/docker-entrypoint.sh
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
EXPOSE 9527
CMD ["/app/docker-entrypoint.sh"]

# Production is an explicit target so legacy development builds remain root
# and can continue writing through compose.yaml's source/database bind mount.
FROM runtime-base AS production
ARG RELEASE_SHA
RUN printf '%s\n' "${RELEASE_SHA:-}" | grep -Eq '^[0-9a-f]{40}$'
LABEL org.opencontainers.image.revision="${RELEASE_SHA}"
ENV HF_HOME=/var/lib/newshub/model-cache \
    HOME=/home/newshub
RUN groupadd --gid 10001 newshub \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/newshub --shell /usr/sbin/nologin newshub \
    && mkdir -p \
        /var/lib/newshub/db \
        /var/lib/newshub/chroma \
        /var/lib/newshub/tts \
        /var/lib/newshub/runtime \
        /var/lib/newshub/model-cache \
        /var/lib/newshub/logs \
    && chown -R 10001:10001 /var/lib/newshub /home/newshub
USER 10001:10001

# Keep the default target aligned with the development compose contract.
FROM runtime-base AS development
USER root
