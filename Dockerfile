FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS base

WORKDIR /app

COPY requirements-build.lock requirements.lock ./
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements-build.lock \
    && python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock

COPY pyproject.toml ./
COPY app ./app

RUN python -m pip install --no-cache-dir --no-deps --no-build-isolation .

RUN groupadd --system --gid 10001 neuromesh \
    && useradd --system --uid 10001 --gid neuromesh --no-create-home neuromesh \
    && mkdir -p /data \
    && chown neuromesh:neuromesh /data

ENV NEUROMESH_STORAGE_BACKEND=sqlite
ENV NEUROMESH_DB_PATH=/data/neuromesh.db

EXPOSE 8000

USER 10001

CMD exec uvicorn app.presentation.api:app --host 0.0.0.0 --port ${PORT:-8000}
