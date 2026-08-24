#!/usr/bin/env bash
set -euo pipefail

# ── VectorDB OEM Platform — One-Command Setup ──
# Usage: ./setup.sh
# Generates .env with secure defaults and starts all services.

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   VectorDB OEM Platform — Self-Hosted Setup  ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Check prerequisites
for cmd in docker; do
  if ! command -v "$cmd" &> /dev/null; then
    echo "Error: $cmd is required but not installed."
    exit 1
  fi
done

if ! docker compose version &> /dev/null; then
  echo "Error: docker compose plugin is required."
  echo "Install it: https://docs.docker.com/compose/install/"
  exit 1
fi

# Generate .env if it doesn't exist
if [ ! -f .env ]; then
  echo -e "${YELLOW}No .env file found — generating one...${NC}"
  cp .env.example .env

  # Auto-generate secure secrets
  DB_PASS=$(openssl rand -hex 16)
  JWT_SEC=$(openssl rand -hex 32)

  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/POSTGRES_PASSWORD=CHANGE_ME/POSTGRES_PASSWORD=${DB_PASS}/" .env
    sed -i '' "s/VDB_JWT_SECRET=CHANGE_ME/VDB_JWT_SECRET=${JWT_SEC}/" .env
  else
    sed -i "s/POSTGRES_PASSWORD=CHANGE_ME/POSTGRES_PASSWORD=${DB_PASS}/" .env
    sed -i "s/VDB_JWT_SECRET=CHANGE_ME/VDB_JWT_SECRET=${JWT_SEC}/" .env
  fi

  echo "  Generated secure database password and JWT secret."
  echo ""
  echo "  An OpenAI API key is OPTIONAL:"
  echo "    - needed only for the 'vector' output (semantic search)"
  echo "    - markdown / SQLite outputs + keyword search work without it"
  echo ""
  read -rp "Paste your OpenAI API key (or press Enter to skip): " api_key
  if [ -n "$api_key" ]; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
      sed -i '' "s|VDB_OPENAI_API_KEY=|VDB_OPENAI_API_KEY=${api_key}|" .env
    else
      sed -i "s|VDB_OPENAI_API_KEY=|VDB_OPENAI_API_KEY=${api_key}|" .env
    fi
    echo "  API key saved."
  else
    echo "  Skipped. You can set VDB_OPENAI_API_KEY in .env later to enable vector search."
  fi
else
  echo -e "${GREEN}.env already exists — using existing configuration.${NC}"
fi

echo ""
echo "Starting services..."
docker compose up -d --build

echo ""
echo "Waiting for API to be healthy..."
for i in {1..30}; do
  if curl -sf http://localhost:${API_PORT:-8000}/health > /dev/null 2>&1; then
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║           Platform is running!                ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo "  Web UI:   http://localhost:${API_PORT:-8000}"
    echo "  API docs: http://localhost:${API_PORT:-8000}/docs"
    echo ""
    echo "Next step: open the Web UI in your browser. It walks you through"
    echo "creating a workspace, uploading documents, choosing what to build"
    echo "(smart search / markdown / SQLite), and creating keys for AI tools."
    echo ""
    exit 0
  fi
  sleep 2
done

echo ""
echo "Warning: API did not respond within 60 seconds."
echo "Check logs: docker compose logs api"
exit 1
