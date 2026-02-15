# VectorDB OEM Platform

Tenant-isolated vector database platform that lets OEMs instantly connect AI automation tools (CRM, customer support, etc.) without weeks of integration work.

## Architecture

```
AI Tools (CRM bots, support agents, etc.)
        │  Query API
        ▼
┌─────────────────────────────────┐
│       API Layer (FastAPI)       │
│  Tenants │ Collections │ Query  │
│  Ingest  │ Connectors           │
├─────────────────────────────────┤
│  Ingestion Pipeline             │
│  (chunking → embedding → store) │
├─────────────────────────────────┤
│  PostgreSQL + pgvector          │
│  (per-tenant namespace isolation)│
└─────────────────────────────────┘
```

## Quick Start

```bash
cp .env.example .env
# Fill in your OPENAI_API_KEY

docker compose up -d
```

## API Usage

### 1. Create a tenant (OEM)

```bash
curl -X POST http://localhost:8000/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "slug": "acme"}'
```

Save the `api_key` from the response — it's only shown once.

### 2. Create a collection

```bash
curl -X POST http://localhost:8000/api/v1/collections \
  -H "X-API-Key: vdb_..." \
  -H "Content-Type: application/json" \
  -d '{"name": "support_tickets", "description": "Customer support ticket history"}'
```

### 3. Ingest data

```bash
curl -X POST http://localhost:8000/api/v1/ingest/text \
  -H "X-API-Key: vdb_..." \
  -H "Content-Type: application/json" \
  -d '{
    "collection_id": "...",
    "source": "ticket-1234",
    "content": "Customer reported login issues after password reset..."
  }'
```

### 4. Query (semantic search)

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: vdb_..." \
  -H "Content-Type: application/json" \
  -d '{
    "collection_id": "...",
    "query": "password reset problems",
    "top_k": 5
  }'
```

### 5. Sync from a connector

```bash
curl -X POST http://localhost:8000/api/v1/connectors/sync \
  -H "X-API-Key: vdb_..." \
  -H "Content-Type: application/json" \
  -d '{
    "connector_type": "example_crm",
    "collection_id": "...",
    "credentials": {"api_token": "test-token"}
  }'
```

## Project Structure

```
src/
  api/          # FastAPI route handlers
  core/         # Config, auth
  connectors/   # Pluggable data source connectors
  db/           # Database session management
  ingestion/    # Chunking and embedding pipeline
  models/       # SQLAlchemy models
```

## Adding a New Connector

1. Create a new file in `src/connectors/`
2. Subclass `BaseConnector` from `src/connectors/base.py`
3. Decorate with `@register_connector`
4. Implement `authenticate()`, `fetch_records()`, and `connector_type`

See `src/connectors/example_crm.py` for a reference implementation.
