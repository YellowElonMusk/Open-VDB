#!/usr/bin/env bash
set -euo pipefail

APP_URL="http://localhost:${API_PORT:-8000}"

echo "Open VDB"
echo "Checking Docker..."
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is required: https://docs.docker.com/get-docker/"
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose is required. It is included with current Docker Desktop."
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
fi

echo "Starting Open VDB..."
docker compose up -d --build

for _ in {1..60}; do
  if curl -sf "$APP_URL/health" >/dev/null 2>&1; then
    echo "Open VDB is ready: $APP_URL"
    case "${OSTYPE:-}" in
      darwin*) open "$APP_URL" >/dev/null 2>&1 || true ;;
      linux*) command -v xdg-open >/dev/null && xdg-open "$APP_URL" >/dev/null 2>&1 || true ;;
    esac
    exit 0
  fi
  sleep 2
done

echo "Open VDB did not become healthy. Run: docker compose logs api"
exit 1
