# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    HF_HOME=/root/.cache/huggingface
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
COPY start_waitress.py /app/start_waitress.py
COPY --chmod=755 scripts/docker-entrypoint.sh /app/docker-entrypoint.sh
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
EXPOSE 9527
CMD ["/app/docker-entrypoint.sh"]
