# syntax=docker/dockerfile:1
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
COPY backend/requirements.txt /app/backend/requirements.txt
ARG TORCH_VERSION=2.14.1+cpu
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==${TORCH_VERSION}" \
    && pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/ /app/backend/
COPY crawler/ /app/crawler/
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
        /var/lib/newshub/logs/crawler \
    && chown -R 10001:10001 /var/lib/newshub /home/newshub
USER 10001:10001

# Keep the default target aligned with the development compose contract.
FROM runtime-base AS development
USER root
