FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Non-root user for production
RUN useradd --create-home appuser

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY . .

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Run DB migrations then start the server
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]
