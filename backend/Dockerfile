FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
# PostgreSQL 18 client tools (pg_dump/pg_restore) from postgresql.org, matching the server (M32 backups).
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates     && install -d /usr/share/postgresql-common/pgdg     && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc     && . /etc/os-release     && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $VERSION_CODENAME-pgdg main"        > /etc/apt/sources.list.d/pgdg.list     && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18     && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
# Cache mount keeps downloaded wheels between builds; retries/timeout survive a slow PyPI connection.
RUN --mount=type=cache,target=/root/.cache/pip pip install --retries 10 --timeout 60 -r requirements.txt
COPY . .
CMD ["sh", "-c", "python -m app.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
