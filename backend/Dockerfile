# CochleaHub API (FastAPI + pipeline CLI) for the AWS deployment (D23).
# Build from the repo root:  docker build -f backend/Dockerfile -t cochleahub-api .
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1

WORKDIR /app
# dependencies first, so code changes do not reinstall them
COPY backend/pyproject.toml backend/
RUN mkdir -p backend/src/cochleahub && touch backend/src/cochleahub/__init__.py \
    && pip install ./backend && pip uninstall -y cochleahub

COPY backend/ backend/
COPY docs/ docs/
# editable install keeps the repo layout (/app/docs, /app/data), which config.REPO_ROOT expects
RUN pip install --no-deps -e ./backend

# run as an unprivileged user
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown -R app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "cochleahub.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
