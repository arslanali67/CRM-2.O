FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
# Cache mount keeps downloaded wheels between builds; retries/timeout survive a slow PyPI connection.
RUN --mount=type=cache,target=/root/.cache/pip pip install --retries 10 --timeout 60 -r requirements.txt
COPY . .
CMD ["sh", "-c", "python -m app.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
