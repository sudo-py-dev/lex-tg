FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra crypto

COPY src ./src
COPY README.md ./
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --frozen --no-dev --extra crypto

FROM python:3.12-slim-bookworm AS runtime-base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN groupadd bot && useradd -g bot -u 1000 -d /app bot \
    && mkdir -p /app/data /app/sessions /app/logs /app/backups /app/tmp \
    && chown -R bot:bot /app

FROM runtime-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    TMPDIR="/app/tmp"

COPY --from=builder --chown=bot:bot /app /app

USER bot
CMD ["python3", "-m", "src.main"]
