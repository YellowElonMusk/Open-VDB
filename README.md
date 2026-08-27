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
- **Try a search** exactly as your AI tools will see it — one hybrid search, with the manual, revision and page shown for every result
- **Create retrieval keys** for AI tools — search-only, clearly explained

Light and dark themes follow your system setting. Connecting with a retrieval key shows a read-only search view.

## API Usage

Everything below can also be done from the web UI — the `curl` commands are for scripting and automation.

Interactive Swagger docs live at `/docs`: click **Authorize**, paste your API key once, and try every endpoint from the browser. The full OpenAPI spec is at `/openapi.json` for Postman imports and client generation. Swagger UI is served from the app itself (no CDN), so `/docs` works air-gapped too.

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
# Natural language — vector, full-text and exact matching all run and fuse
curl -X POST http://localhost:8000/api/v1/retrieve \
  -H "X-API-Key: vdb_ret_..." \
  -H "Content-Type: application/json" \
  -d '{"query": "how to reset the hydraulic pressure valve", "top_k": 5}'

# An exact fault code — the same endpoint, no mode to choose.
curl -X POST http://localhost:8000/api/v1/retrieve \
  -H "X-API-Key: vdb_ret_..." \
  -H "Content-Type: application/json" \
  -d '{"query": "AF-01-3021-6-1", "top_k": 5}'
```

Response — only the relevant snippets:

```json
{
  "snippets": [
    {
      "content": "6.1 FAULT CODES\nCODE | DESCRIPTION | ACTION\nCODE: AF-01-3021-6-1; DESCRIPTION: Slope is too steep; ACTION: Push robot away from slope and try again",
      "source_filename": "R3-Vac-Manuel-Entretien-Ed.01-v0.6.pdf",
      "relevance_score": 1.0,
      "page": 1,
      "section": "6.1 FAULT CODES",
      "source_doc": "R3 Vac",
      "revision": "Ed.01 v0.6",
      "needs_review": true
    }
  ],
  "query": "AF-01-3021-6-1"
}
```

Every snippet carries the manual, revision, page and section so the agent can cite what it quotes. `needs_review` is true when sources disagreed on facts in that text — here, because an adjacent fault code states nearly the same sentence.

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
| `VDB_CHUNK_SIZE` | No | `512` | Legacy chunk size (prose now targets ~1200 chars per section) |
| `VDB_QUALITY_GATE_ENABLED` | No | `true` | Reject documents whose extraction fails quality checks |
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
2. **Parse**: PyMuPDF extracts text at *span* level with an explicit space guard, and `find_tables()` recovers real table structure. Each table row becomes one unit with its header bound to every value (`PROBLEM: THE ROBOT DOES NOT START; POSSIBLE CAUSE: …`). Headings are detected by font size and weight, and every unit is stamped with its section, page, source document and revision.
3. **Quality gate**: the extraction is measured before anything is built from it — fused words, orphan pipes, blank-line padding, minimum length. A document that fails is marked `failed` with the metrics in `error_message` rather than shipped looking healthy.
4. **Chunk**: structure-aware. A table row is one chunk, never split, always carrying its header — a fault code can never be separated from its description. Prose is packed to ~1200 characters within section boundaries with the heading prepended.
5. **Deduplicate**: near-duplicates across a manual, its quick guide and its wallchart are collapsed by MinHash/LSH — but only when their *fact fingerprints* (every number, unit, tolerance and code) match exactly. Chunks that read alike but state different facts are all kept and flagged `needs_review`.
6. **Build the chosen outputs**:
   - `vector`: each surviving chunk is embedded and stored in pgvector (HNSW index)
   - `markdown`: a `.md` export with YAML front matter, real `##` headings, GFM tables and provenance comments
   - `sqlite`: a `.db` export with chunk metadata, an FTS5 index, and a dedicated `fault_codes` table
7. **Retrieve**: hybrid search, always. Vector similarity, Postgres full-text search and trigram-indexed exact matching all run, and their rankings are fused with reciprocal rank fusion.

The AI tool never sees the full document via the retrieval API. It gets exactly the paragraphs relevant to its question, each carrying the manual, revision, page and section to cite.

### Why hybrid retrieval, and not a `mode` parameter

An agent asked to choose between "semantic" and "keyword" will sometimes choose wrong, and a wrong choice returns a confident wrong answer rather than an obvious failure. So every query runs all three legs:

| Leg | Finds | Index |
|-----|-------|-------|
| `exact` | fault codes, part numbers | GIN trigram on `content` |
| `fts` | words, stemmed per language | GIN on a generated `tsvector` (English **and** French) |
| `vector` | meaning | HNSW `vector_cosine_ops` |

`mode` is still accepted so existing clients keep working, but it is ignored and logs a deprecation warning.

### Fault codes are looked up, never inferred

The generated SQLite file carries a `fault_codes(code, description, source_doc, page)` table:

```sql
SELECT description, source_doc, page FROM fault_codes WHERE code = 'AF-01-3021-6-1';
```

An exact SQL lookup returns that code or nothing. A similarity search over ~180 codes across ~70 prefix families will happily return `AF-01-3022-6-1` instead — a different fault with a different fix.

## Extraction Quality

Ingestion measures itself. `samples/` holds two representative manuals (English and French); `scripts/quality_report.py` runs both the current pipeline and a reproduction of the previous one over them and prints the delta:

```bash
python scripts/make_samples.py     # regenerate the sample manuals
python scripts/quality_report.py   # before/after metrics
```

| Metric | Before | After |
|--------|-------:|------:|
| Fused words per 1k words | 1.77 | **0** |
| Orphan pipe line ratio | 0.053 | **0.027** |
| Blank line ratio | 0.149 | **0** |
| Headings recovered | 0 | **13** |
| Header-bound table rows | 0 | **30** |

The gate is on by default. Set `VDB_QUALITY_GATE_ENABLED=false` to bypass it deliberately — never accidentally.

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
    parser.py       # PyMuPDF span-level extraction → structured Blocks
    quality_gate.py # Fused words, orphan pipes, blank padding — pass/fail
    dedup.py        # MinHash/LSH grouping + fact fingerprints
    exporters.py    # Markdown and SQLite (FTS5 + fault_codes) builders
    pipeline.py     # parse → assess → chunk → dedup → build outputs
  models/
    database.py   # SQLAlchemy models (Tenant, ApiKey, Document, Chunk, Artifact)
  db/
    session.py    # Async database session
    bootstrap.py  # Runs Alembic migrations on startup (idempotent)
alembic/versions/ # Every schema change, including the hybrid search DDL
samples/          # Representative EN + FR manuals for quality benchmarking
scripts/
  make_samples.py   # Regenerate the sample manuals
  quality_report.py # Before/after extraction metrics
```
