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
  echo -e "${YELLOW}ACTION REQUIRED: Add your OpenAI API key to .env${NC}"
  echo "  Edit .env and set VDB_OPENAI_API_KEY=sk-..."
  echo ""

  # Check if the key is still placeholder
  if grep -q "sk-your-key-here" .env; then
    read -rp "Paste your OpenAI API key now (or press Enter to set later): " api_key
    if [ -n "$api_key" ]; then
      if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|VDB_OPENAI_API_KEY=sk-your-key-here|VDB_OPENAI_API_KEY=${api_key}|" .env
      else
        sed -i "s|VDB_OPENAI_API_KEY=sk-your-key-here|VDB_OPENAI_API_KEY=${api_key}|" .env
      fi
      echo "  API key saved."
    else
      echo "  Skipped. Remember to set it in .env before uploading documents."
    fi
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
    echo "  API:   http://localhost:${API_PORT:-8000}"
    echo "  Docs:  http://localhost:${API_PORT:-8000}/docs"
    echo ""
    echo "Next steps:"
    echo "  1. Create your first OEM tenant:"
    echo "     curl -X POST http://localhost:${API_PORT:-8000}/api/v1/tenants \\"
    echo '       -H "Content-Type: application/json" \\'
    echo "       -d '{\"name\": \"My Company\", \"slug\": \"my-company\"}'"
    echo ""
    echo "  2. Upload a document with the admin key from step 1"
    echo "  3. Create a retrieval key and hand it to your AI tool"
    echo ""
    exit 0
  fi
  sleep 2
done

echo ""
echo "Warning: API did not respond within 60 seconds."
echo "Check logs: docker compose logs api"
exit 1
