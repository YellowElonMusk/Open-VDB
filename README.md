# VectorDB OEM Platform

**Self-hosted vector database for OEMs. Deploy on your infrastructure. Your data never leaves your network.**

Upload your manuals, guides, and SOPs — get an instant vector database. AI SaaS tools retrieve only the specific snippets they need. No proprietary documents ever leave your environment.

## Why Self-Hosted?

OEMs deal with sensitive IP: service manuals, engineering specs, SOPs. Sending that to a third-party cloud means compliance headaches, legal review, and $30K+ audit cycles before you can even pilot an AI tool.

**Self-hosted means none of that.** You run this on your own servers (or your own cloud account). Your compliance team already covers your infrastructure. No BAAs, no SOC 2 audits, no data processing agreements — just `docker compose up` and go.

```
┌─────────────────────────────────────────────────┐
│              YOUR INFRASTRUCTURE                 │
│                                                  │
│   ┌─────────┐  ┌──────────┐  ┌──────────────┐  │
│   │   API   │  │ Postgres │  │    Redis     │  │
│   │ Server  │──│ +pgvector│  │   (cache)    │  │
│   └────┬────┘  └──────────┘  └──────────────┘  │
│        │                                         │
│        ▼                                         │
│   OEM uploads docs → auto-parsed, chunked,       │
│   embedded, stored. AI tools get snippets only.  │
│                                                  │
│   Only outbound call: OpenAI Embeddings API      │
│   (uses YOUR API key)                            │
└─────────────────────────────────────────────────┘
```

## Quick Start (One Command)

```bash
git clone <repo-url> && cd vectordb-oem
./setup.sh
```

The setup script will:
- Generate secure database passwords and JWT secrets
- Prompt you for your OpenAI API key
- Start PostgreSQL (with pgvector), Redis, and the API server
- Wait for health checks and print your API URL

**Or manually:**

```bash
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, VDB_OPENAI_API_KEY, VDB_JWT_SECRET
docker compose up -d
```

The API is ready at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## API Usage

### 1. Create your OEM tenant

```bash
curl -X POST http://localhost:8000/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "slug": "acme"}'
```

Save the `admin_api_key` — it's shown only once.

### 2. Upload your documents

```bash
# Single file
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "X-API-Key: vdb_adm_..." \
  -F "file=@service-manual.pdf"

# Multiple files at once
curl -X POST http://localhost:8000/api/v1/documents/upload/batch \
  -H "X-API-Key: vdb_adm_..." \
  -F "files=@manual.pdf" \
  -F "files=@sop-guide.docx" \
  -F "files=@faq.txt"
```

Files are automatically parsed, chunked, embedded, and indexed.

### 3. Create a retrieval key for your AI tool

```bash
curl -X POST http://localhost:8000/api/v1/tenants/keys \
  -H "X-API-Key: vdb_adm_..." \
  -H "Content-Type: application/json" \
  -d '{"label": "CRM Bot", "scope": "retrieval"}'
```

Give the `vdb_ret_...` key to the AI SaaS tool. It can only search — never upload, delete, or see full documents.

### 4. AI tool retrieves what it needs

```bash
curl -X POST http://localhost:8000/api/v1/retrieve \
  -H "X-API-Key: vdb_ret_..." \
  -H "Content-Type: application/json" \
  -d '{"query": "how to reset the hydraulic pressure valve", "top_k": 5}'
```

Response — only the relevant snippets:

```json
{
  "snippets": [
    {
      "content": "To reset the hydraulic pressure valve, first ensure the system is depressurized. Locate valve HPV-200 on the main assembly...",
      "source_filename": "service-manual.pdf",
      "relevance_score": 0.94
    }
  ],
  "query": "how to reset the hydraulic pressure valve"
}
```

## Deployment Models

### On-Premise Server

Run directly on a Linux server with Docker installed. Ideal for air-gapped or restricted environments (only outbound traffic is to OpenAI's embeddings API).

```bash
# Minimum requirements: 2 CPU, 4 GB RAM, 20 GB disk
./setup.sh
```

### Cloud VM (AWS / GCP / Azure)

Spin up a VM in your own cloud account. Your cloud compliance posture covers the data.

```bash
# Example: AWS EC2
ssh your-server
git clone <repo-url> && cd vectordb-oem
./setup.sh
```

### Behind a Reverse Proxy (Production)

For TLS termination, put nginx/Caddy/Traefik in front:

```bash
# In .env, change the API port if needed:
API_PORT=8080

# Then point your reverse proxy at localhost:8080
```

## Data Privacy Model

| What | Where it lives | Who can access |
|------|---------------|----------------|
| Uploaded documents | Your PostgreSQL instance | Admin API key holders only |
| Text chunks + embeddings | Your PostgreSQL instance | Admin + retrieval key holders |
| Full document content | Never exposed via API | Nobody via the retrieval endpoint |
| AI tool queries | Your server logs only | Your ops team |
| Embedding vectors | Computed via OpenAI API | Sent to OpenAI, subject to their data policy |

The only external call is to OpenAI's embeddings API (using your key). If you need fully air-gapped operation, swap in a local embedding model (see Configuration below).

## Configuration

All configuration is via environment variables (prefix `VDB_` for app settings):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTGRES_PASSWORD` | Yes | — | Database password |
| `VDB_OPENAI_API_KEY` | Yes | — | Your OpenAI API key (BYOK) |
| `VDB_JWT_SECRET` | Yes | — | Secret for token signing |
| `POSTGRES_USER` | No | `vectordb` | Database username |
| `POSTGRES_DB` | No | `vectordb_oem` | Database name |
| `API_PORT` | No | `8000` | Host port for the API |
| `UVICORN_WORKERS` | No | `2` | API server worker count |
| `VDB_DEBUG` | No | `false` | Enable debug logging |
| `VDB_EMBEDDING_MODEL` | No | `text-embedding-3-small` | OpenAI embedding model |
| `VDB_CHUNK_SIZE` | No | `512` | Text chunk size (chars) |
| `VDB_MAX_UPLOAD_SIZE_MB` | No | `50` | Max file upload size |

## Two Types of API Keys

| Key Type | Prefix | Can Upload | Can Delete | Can Search | Who Uses It |
|----------|--------|-----------|-----------|-----------|-------------|
| Admin    | `vdb_adm_` | Yes | Yes | Yes | OEM team |
| Retrieval | `vdb_ret_` | No | No | Yes | AI SaaS tools |

This separation ensures AI tools only access the minimum information they need.

## Supported File Formats

- **PDF** — manuals, spec sheets, technical docs (enhanced for tables and multi-column layouts)
- **DOCX** — Word documents, SOPs, procedures (with table extraction)
- **TXT** — plain text guides, notes
- **CSV** — structured data (parts lists, error codes, etc.)
- **Markdown** — documentation, knowledge bases

## How It Works Under the Hood

1. **Upload**: OEM uploads a PDF/DOCX/TXT file
2. **Parse**: Text is extracted (with table and layout awareness for manufacturing docs)
3. **Chunk**: Text is split into overlapping ~512-char chunks at sentence boundaries
4. **Embed**: Each chunk is converted to a 1536-dim vector via OpenAI embeddings
5. **Store**: Chunks + vectors stored in PostgreSQL with pgvector
6. **Retrieve**: AI tool sends a natural language query → embedded → cosine similarity search → top-k chunks returned

The AI tool never sees the full document. It gets exactly the paragraphs relevant to its question.

## Operations

```bash
# View logs
docker compose logs -f api

# Restart after config change
docker compose restart api

# Stop everything (data persists in volumes)
docker compose down

# Full reset (destroys all data)
docker compose down -v

# Health check
curl http://localhost:8000/health
```

## Project Structure

```
src/
  api/
    tenants.py    # OEM onboarding, API key management
    upload.py     # File upload (single + batch)
    retrieve.py   # Semantic search for AI SaaS tools
    schemas.py    # Request/response models
  core/
    config.py     # Environment configuration
    auth.py       # API key auth with admin/retrieval scoping
  ingestion/
    parser.py     # PDF, DOCX, TXT, CSV, MD text extraction
    pipeline.py   # chunk → embed → store pipeline
  models/
    database.py   # SQLAlchemy models (Tenant, ApiKey, Document, Chunk)
  db/
    session.py    # Async database session
```
