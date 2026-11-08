# One image for every backend role: API, Celery worker, Celery beat and the migrate job.
# Build context: repository root.

# ---- build: install production dependencies into an isolated virtualenv ----
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# ---- runtime ----
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    WEB_CONCURRENCY=2

RUN groupadd --system radar && useradd --system --gid radar --home-dir /app --shell /usr/sbin/nologin radar

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
# Only what runs in production: no tests, no local virtualenvs, no .env files.
COPY --chown=radar:radar backend/app ./app
COPY --chown=radar:radar backend/workers ./workers
COPY --chown=radar:radar backend/alembic ./alembic
COPY --chown=radar:radar backend/alembic.ini ./alembic.ini

USER radar
EXPOSE 8000

# Liveness of the API process. Worker/beat containers override this in compose.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4)" || exit 1

# --proxy-headers: trust X-Forwarded-* from the reverse proxy in front (the API is not
# published directly; only the proxy can reach it on the internal network).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
