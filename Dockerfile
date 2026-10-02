FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN groupadd --system --gid 10001 neuromesh \
    && useradd --system --uid 10001 --gid neuromesh --no-create-home neuromesh \
    && mkdir -p /data \
    && chown neuromesh:neuromesh /data

ENV NEUROMESH_STORAGE_BACKEND=sqlite
ENV NEUROMESH_DB_PATH=/data/neuromesh.db

EXPOSE 8000

USER 10001

CMD exec uvicorn app.presentation.api:app --host 0.0.0.0 --port ${PORT:-8000}
