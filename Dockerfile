# WiseQ Hermes -- single-service image.
#
# Deliberately small: no bundled database server, no bundled mail server.
# Supabase (or any PostgreSQL) and MailHog are separate services in
# docker-compose.yml, so the app image stays portable and replaceable.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# psycopg2 needs libpq; build-essential is only needed for the wheel build
# and is removed again in the same layer.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY scripts ./scripts
COPY tests ./tests

# The client's master data is mounted, never baked into the image.
ENV WISEQ_REPO_DIR=/data/wiseq-repo \
    WISEQ_DATABASE_URL=sqlite:////data/wiseq.db \
    WISEQ_API_HOST=0.0.0.0 \
    WISEQ_API_PORT=8000

RUN mkdir -p /data \
 && useradd --uid 10001 --create-home wiseq \
 && chown -R wiseq:wiseq /data /app
USER wiseq

EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["sh", "-c", "uvicorn wiseq.api:app --host ${WISEQ_API_HOST:-0.0.0.0} --port ${WISEQ_API_PORT:-8000}"]
