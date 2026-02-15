# VectorDB OEM Platform

**Upload your manuals, guides, and SOPs — get an instant vector database.**

OEMs upload their documentation once. AI SaaS tools (CRM bots, support agents, automation platforms) retrieve only the specific snippets they need to function — never your full proprietary documents.

## The Problem

When OEMs want to try AI automation tools, they face weeks of integration work: extracting data from manuals, formatting it, setting up vector databases, managing embeddings. Meanwhile, handing full documents to AI tools exposes proprietary information the tools don't even need.

## The Solution

```
OEM uploads files (PDF, DOCX, TXT, CSV, MD)
        │
        ▼
┌──────────────────────────────────┐
│  Automatic Processing Pipeline   │
│  parse → chunk → embed → store   │
├──────────────────────────────────┤
│  Secure Vector Database          │
│  (per-tenant isolation)          │
├──────────────────────────────────┤
│  Retrieval API                   │
│  AI tools get ONLY relevant      │
│  snippets, never full docs       │
└──────────────────────────────────┘
        │
        ▼
AI SaaS tools call /retrieve with a question,
get back just the 3-5 text snippets they need
```

## Quick Start

```bash
cp .env.example .env
# Fill in your OPENAI_API_KEY

docker compose up -d
```

## API Usage

### Step 1: Register your OEM

```bash
curl -X POST http://localhost:8000/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "slug": "acme"}'
```

Save the `admin_api_key` — it's shown only once.

### Step 2: Upload your documents

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

That's it. The platform automatically parses, chunks, embeds, and indexes your documents.

### Step 3: Create a retrieval key for your AI tool

```bash
curl -X POST http://localhost:8000/api/v1/tenants/keys \
  -H "X-API-Key: vdb_adm_..." \
  -H "Content-Type: application/json" \
  -d '{"label": "CRM Bot", "scope": "retrieval"}'
```

Give the `vdb_ret_...` key to the AI SaaS tool. It can only search — never upload, delete, or see full documents.

### Step 4: AI tool retrieves what it needs

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

## Two Types of API Keys

| Key Type | Prefix | Can Upload | Can Delete | Can Search | Who Uses It |
|----------|--------|-----------|-----------|-----------|-------------|
| Admin    | `vdb_adm_` | Yes | Yes | Yes | OEM team |
| Retrieval | `vdb_ret_` | No | No | Yes | AI SaaS tools |

This separation ensures AI tools only access the minimum information they need.

## Supported File Formats

- **PDF** — manuals, spec sheets, technical docs
- **DOCX** — Word documents, SOPs, procedures
- **TXT** — plain text guides, notes
- **CSV** — structured data (parts lists, error codes, etc.)
- **Markdown** — documentation, knowledge bases

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

## How It Works Under the Hood

1. **Upload**: OEM uploads a PDF/DOCX/TXT file
2. **Parse**: Text is extracted from the file format
3. **Chunk**: Text is split into overlapping ~512-char chunks at sentence boundaries
4. **Embed**: Each chunk is converted to a 1536-dim vector via OpenAI embeddings
5. **Store**: Chunks + vectors stored in PostgreSQL with pgvector
6. **Retrieve**: AI tool sends a natural language query → embedded → cosine similarity search → top-k chunks returned

The AI tool never sees the full document. It gets exactly the paragraphs relevant to its question.
