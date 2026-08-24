# VectorDB OEM Platform

**Self-hosted document database builder for OEMs. Deploy on your infrastructure. Your data never leaves your network.**

Upload your manuals, guides, and SOPs — choose what to build from them:

| Output | What you get | When to use it | Needs OpenAI key? |
|--------|-------------|----------------|-------------------|
| `vector` | Semantic search API (pgvector) | Natural language questions over large manuals (RAG) | Yes |
| `markdown` | Clean `.md` file download | Simple docs an agent can read whole (FAQs, short SOPs) | No |
| `sqlite` | Standalone SQLite `.db` file with full-text search | Exact lookups — error codes, part numbers, model names | No |

Not everything needs a vector database. Matching a robot error code to its fix in an FAQ is a lookup, not a semantic search — a Markdown file or a SQLite file your AI agent reads locally is simpler, free, and fully offline. Pick any combination per upload; AI SaaS tools still retrieve only the specific snippets they need, and no proprietary documents ever leave your environment.

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
│   then built into the outputs YOU choose:        │
│   vector search, .md files, SQLite .db files.    │
│   AI tools get snippets only.                    │
│                                                  │
│   Only outbound call (optional): OpenAI          │
│   Embeddings API for the 'vector' output.        │
│   markdown/sqlite outputs are fully offline.     │
└─────────────────────────────────────────────────┘
```

## Quick Start (One Command)

```bash
git clone <repo-url> && cd vectordb-oem
./setup.sh
```

The setup script will:
- Generate secure database passwords and JWT secrets
- Optionally take your OpenAI API key (only needed for the `vector` output — press Enter to skip and use markdown/sqlite outputs fully offline)
- Start PostgreSQL (with pgvector), Redis, and the API server
- Create the database schema automatically
- Wait for health checks and print your API URL

**Or manually:**

```bash
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD and VDB_JWT_SECRET
# (VDB_OPENAI_API_KEY is optional — only for the 'vector' output)
docker compose up -d
```

Then open **`http://localhost:8000`** in your browser — the built-in web UI walks you through everything with no code: create your workspace, drag-and-drop documents, pick which outputs to build, download the generated `.md`/`.db` files, try searches, and create keys for your AI tools. API reference at `http://localhost:8000/docs`.

## Web UI

The UI ships with the server — no separate install, no Node, no build step, and it works air-gapped (no external fonts or scripts).

- **Create a workspace** on first visit (or connect with an existing key); your admin key is shown once — save it
- **Add documents** by drag-and-drop and choose what to build: smart search database, Markdown file, SQLite file
- **Download** per-document exports or everything as one SQLite/Markdown file
- **Try a search** exactly as your AI tools will see it — Smart (semantic) or Exact (error codes) mode
- **Create retrieval keys** for AI tools — search-only, clearly explained

Light and dark themes follow your system setting. Connecting with a retrieval key shows a read-only search view.

## API Usage

Everything below can also be done from the web UI — the `curl` commands are for scripting and automation.

### 1. Create your OEM tenant

```bash
curl -X POST http://localhost:8000/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "slug": "acme"}'
```

Save the `admin_api_key` — it's shown only once.

### 2. Upload your documents and choose the outputs

The `outputs` field picks what gets built — any combination of `vector`, `markdown`, `sqlite`. It defaults to `vector` if omitted.

```bash
# Big service manual → vector database for semantic search (RAG)
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "X-API-Key: vdb_adm_..." \
  -F "file=@service-manual.pdf" \
  -F "outputs=vector"

# Error-code FAQ → markdown + SQLite files, no OpenAI key needed
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "X-API-Key: vdb_adm_..." \
  -F "file=@error-code-faq.pdf" \
  -F "outputs=markdown,sqlite"

# Everything at once — the outputs apply to every file in the batch
curl -X POST http://localhost:8000/api/v1/documents/upload/batch \
  -H "X-API-Key: vdb_adm_..." \
  -F "files=@manual.pdf" \
  -F "files=@sop-guide.docx" \
  -F "files=@faq.txt" \
  -F "outputs=vector,markdown,sqlite"
```

Files are automatically parsed, chunked, and built into the outputs you chose.

### 3. Download the generated files (markdown / sqlite outputs)

```bash
# One document as a clean .md file
curl -OJ http://localhost:8000/api/v1/documents/<document-id>/export/markdown \
  -H "X-API-Key: vdb_adm_..."

# One document as a standalone SQLite .db file
curl -OJ http://localhost:8000/api/v1/documents/<document-id>/export/sqlite \
  -H "X-API-Key: vdb_adm_..."

# ALL documents in one SQLite .db (works for every upload, any outputs choice)
curl -OJ http://localhost:8000/api/v1/export/sqlite \
  -H "X-API-Key: vdb_adm_..."

# All markdown exports bundled into a single .md file
curl -OJ http://localhost:8000/api/v1/export/markdown \
  -H "X-API-Key: vdb_adm_..."
```

Hand the `.md` or `.db` file to your local AI agent. The SQLite file is self-contained with an FTS5 full-text index — query it with any SQLite client, no server needed:

```sql
SELECT c.content, d.filename
FROM chunks_fts f
JOIN chunks c ON c.id = f.rowid
JOIN documents d ON d.id = c.document_id
WHERE chunks_fts MATCH '"E-042"'
ORDER BY rank LIMIT 5;
```

### 4. Create a retrieval key for your AI tool

```bash
curl -X POST http://localhost:8000/api/v1/tenants/keys \
  -H "X-API-Key: vdb_adm_..." \
  -H "Content-Type: application/json" \
  -d '{"label": "CRM Bot", "scope": "retrieval"}'
```

Give the `vdb_ret_...` key to the AI SaaS tool. It can only search — never upload, delete, or see full documents.

### 5. AI tool retrieves what it needs

```bash
# Semantic search (documents uploaded with the 'vector' output)
curl -X POST http://localhost:8000/api/v1/retrieve \
  -H "X-API-Key: vdb_ret_..." \
  -H "Content-Type: application/json" \
  -d '{"query": "how to reset the hydraulic pressure valve", "top_k": 5}'

# Keyword search — exact matching for error codes and part numbers.
# Works for EVERY document, no embeddings or OpenAI key required.
curl -X POST http://localhost:8000/api/v1/retrieve \
  -H "X-API-Key: vdb_ret_..." \
  -H "Content-Type: application/json" \
  -d '{"query": "E-042", "top_k": 5, "mode": "keyword"}'
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

Run directly on a Linux server with Docker installed. Ideal for air-gapped or restricted environments — with markdown/sqlite outputs and keyword search there is **zero** outbound traffic; the optional `vector` output adds a single outbound call to OpenAI's embeddings API.

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
| Generated .md / .db exports | Your PostgreSQL instance | Admin API key holders only |
| Full document content | Never exposed via retrieval API | Nobody via the retrieval endpoint |
| AI tool queries | Your server logs only | Your ops team |
| Embedding vectors (`vector` output only) | Computed via OpenAI API | Sent to OpenAI, subject to their data policy |

The only external call is to OpenAI's embeddings API (using your key), and only when a document is uploaded with the `vector` output. For fully air-gapped operation, use the `markdown`/`sqlite` outputs with keyword search — no external calls at all.

## Configuration

All configuration is via environment variables (prefix `VDB_` for app settings):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTGRES_PASSWORD` | Yes | — | Database password |
| `VDB_OPENAI_API_KEY` | No | — | OpenAI API key (BYOK) — only needed for the `vector` output |
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

1. **Upload**: OEM uploads a PDF/DOCX/TXT file and picks the outputs (`vector`, `markdown`, `sqlite`)
2. **Parse**: Text is extracted (with table and layout awareness for manufacturing docs)
3. **Chunk**: Text is split into overlapping ~512-char chunks at sentence boundaries — chunks are always stored, so keyword search works for every document
4. **Build the chosen outputs**:
   - `vector`: each chunk is converted to a 1536-dim vector via OpenAI embeddings and stored in pgvector
   - `markdown`: a clean `.md` export is generated and stored for download
   - `sqlite`: a standalone `.db` export (chunks + FTS5 full-text index) is generated and stored for download
5. **Retrieve**: AI tool sends a query → `mode=semantic` (cosine similarity over embeddings) or `mode=keyword` (exact text match, great for error codes) → top-k chunks returned. Or skip the API entirely and hand your agent the downloaded `.md`/`.db` files.

The AI tool never sees the full document via the retrieval API. It gets exactly the paragraphs relevant to its question.

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
static/
  index.html      # Web UI (no build step — served by the API at /)
  styles.css
  app.js
src/
  api/
    tenants.py    # OEM onboarding, API key management
    upload.py     # File upload (single + batch) with output selection
    export.py     # Download generated .md / SQLite .db files
    retrieve.py   # Semantic + keyword search for AI SaaS tools
    schemas.py    # Request/response models
  core/
    config.py     # Environment configuration
    auth.py       # API key auth with admin/retrieval scoping
  ingestion/
    parser.py     # PDF, DOCX, TXT, CSV, MD text extraction
    exporters.py  # Markdown and SQLite (FTS5) export builders
    pipeline.py   # chunk → build chosen outputs pipeline
  models/
    database.py   # SQLAlchemy models (Tenant, ApiKey, Document, Chunk, Artifact)
  db/
    session.py    # Async database session
    bootstrap.py  # Idempotent schema creation (runs on startup)
```
