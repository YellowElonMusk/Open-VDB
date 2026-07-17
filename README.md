# Open VDB

**Download it, start it, drag in your files, and search them.**

Open VDB turns PDF, DOCX, TXT, CSV, and Markdown files into a private searchable vector database. The default mode is local, free, and requires no API key.

## Start in two steps

### Windows

1. Install Docker Desktop.
2. Download this repository, unzip it, and double-click `setup.bat`.

### macOS or Linux

```bash
./setup.sh
```

Open VDB launches at **http://localhost:8000**. Drop files into the browser and search immediately.

The app binds to `127.0.0.1` by default, so other devices on your network cannot access it.

## What happens automatically

1. A private local workspace is created.
2. Files are parsed and split into useful overlapping chunks.
3. Chunks are embedded and stored in PostgreSQL with pgvector.
4. The built-in search interface retrieves the most relevant snippets.

No tenant setup, curl commands, API-key copying, or separate frontend is required in local mode.

## Embedding modes

### Local — default

```env
VDB_EMBEDDING_PROVIDER=local
```

Works offline with no account or usage fees. It uses deterministic feature hashing, which is effective for manuals, error codes, part names, and keyword-heavy technical documentation.

### OpenAI — optional

```env
VDB_EMBEDDING_PROVIDER=openai
VDB_OPENAI_API_KEY=sk-...
```

Provides stronger semantic matching. Document chunks and search queries are sent to the OpenAI embeddings API, so this mode is not fully offline.

After changing `.env`, restart:

```bash
docker compose up -d --build
```

## Supported files

- PDF
- DOCX
- TXT
- CSV
- Markdown

Default limits are 50 MB per file and 50 files per batch.

## API mode

The REST API remains available at `http://localhost:8000/docs` for integrations. For a network or production deployment:

```env
VDB_LOCAL_MODE=false
VDB_BIND_ADDRESS=0.0.0.0
```

Create a tenant through `/api/v1/tenants`, keep the returned admin key private, and create retrieval-only keys for external tools. Put TLS and authentication controls in front of any internet-facing deployment.

## Useful commands

```bash
# Logs
docker compose logs -f api

# Stop while keeping data
docker compose down

# Restart
docker compose up -d

# Delete all local data
docker compose down -v
```

## Architecture

```text
Browser drag-and-drop UI
        |
        v
FastAPI upload and retrieval API
        |
        +--> document parser
        +--> chunking and embeddings
        v
PostgreSQL + pgvector
```

The default stack intentionally excludes Redis and other unused services to minimize setup time and failure points.
