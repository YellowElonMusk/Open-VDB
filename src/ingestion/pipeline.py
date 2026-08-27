"""Ingestion pipeline: parse → assess → chunk → dedup → build outputs.

OEMs upload a file and choose what it becomes:

- vector:   chunks are embedded and stored in pgvector (semantic search)
- markdown: a clean .md export is generated for direct agent consumption
- sqlite:   a standalone SQLite .db export with an FTS5 keyword index

Chunking is structure-aware. A table row is one chunk, never split, with
its header bound to it — a fault code and its description must never land
in different chunks. Prose is packed within section boundaries and every
chunk carries the heading it lives under.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import openai
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.ingestion import quality_gate
from src.ingestion.dedup import deduplicate
from src.ingestion.exporters import (
    FORMAT_MARKDOWN,
    FORMAT_SQLITE,
    FORMAT_VECTOR,
    build_markdown,
    build_sqlite,
    export_stem,
)
from src.ingestion.parser import (
    KIND_HEADING,
    KIND_TABLE,
    Block,
    detect_language,
    parse_file,
)
from src.models.database import Artifact, Chunk, Document

# Prose target. Large enough to hold a whole procedure, small enough that a
# retrieved snippet stays readable in an agent's context.
PROSE_TARGET_CHARS = 1200
# A single block longer than this is split at sentence boundaries.
PROSE_SPLIT_CHARS = int(PROSE_TARGET_CHARS * 1.5)


@dataclass
class ChunkDraft:
    """A chunk before embedding, carrying the structure it came from."""

    text: str
    page: int = 1
    section: str = ""
    kind: str = "prose"
    source_doc: str = ""
    revision: str = ""
    lang: str = "en"
    provenance: list[str] = field(default_factory=list)
    needs_review: bool = False

    @property
    def citation(self) -> str:
        parts = [p for p in (self.source_doc, self.revision) if p]
        parts.append(f"p.{self.page}")
        return " ".join(parts)


def assessment_text(blocks: list[Block]) -> str:
    """Render blocks for quality assessment — one unit per line.

    Deliberately not blocks_to_text(): padding every unit with a blank line
    would make the blank-line metric measure the renderer, not the parse.
    """
    return "\n".join(block.text for block in blocks if block.text.strip())


def _table_chunk_text(block: Block) -> str:
    """Table row with its section and column names attached."""
    lines = []
    if block.section:
        lines.append(block.section)
    if block.table_header:
        header = [cell for cell in block.table_header if cell]
        if header:
            lines.append(" | ".join(header))
    lines.append(block.text)
    return "\n".join(lines)


def _split_long_prose(text: str) -> list[str]:
    """Split an oversized paragraph at sentence boundaries."""
    sentences = []
    buffer = ""
    for piece in text.replace("! ", "!\x00").replace("? ", "?\x00").replace(". ", ".\x00").split("\x00"):
        if len(buffer) + len(piece) + 1 > PROSE_TARGET_CHARS and buffer:
            sentences.append(buffer.strip())
            buffer = ""
        buffer += piece + " "
    if buffer.strip():
        sentences.append(buffer.strip())
    return sentences or [text]


def chunk_text(blocks: list[Block], lang: str = "en") -> list[ChunkDraft]:
    """Turn parsed blocks into chunks that preserve document structure."""
    drafts: list[ChunkDraft] = []
    buffer: list[Block] = []

    def flush_prose():
        nonlocal buffer
        if not buffer:
            return
        section = buffer[0].section
        body = " ".join(block.text for block in buffer).strip()
        head = buffer[0]
        for piece in (_split_long_prose(body) if len(body) > PROSE_SPLIT_CHARS else [body]):
            text = f"{section}\n\n{piece}" if section else piece
            drafts.append(
                ChunkDraft(
                    text=text,
                    page=head.page,
                    section=section,
                    kind="prose",
                    source_doc=head.source_doc,
                    revision=head.revision,
                    lang=lang,
                )
            )
        buffer = []

    for block in blocks:
        if block.kind == KIND_HEADING:
            # The heading itself is not a chunk; it prefixes the chunks of
            # its section.
            flush_prose()
            continue

        if block.kind == KIND_TABLE:
            flush_prose()
            drafts.append(
                ChunkDraft(
                    text=_table_chunk_text(block),
                    page=block.page,
                    section=block.section,
                    kind="table",
                    source_doc=block.source_doc,
                    revision=block.revision,
                    lang=lang,
                )
            )
            continue

        if buffer and (
            block.section != buffer[0].section
            or sum(len(b.text) for b in buffer) + len(block.text) > PROSE_TARGET_CHARS
        ):
            flush_prose()
        buffer.append(block)

    flush_prose()

    for draft in drafts:
        draft.provenance = [draft.citation]
    return drafts


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings via OpenAI. Batches automatically."""
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    return [item.embedding for item in response.data]


async def process_upload(
    db: AsyncSession,
    document: Document,
    file_content: bytes,
    formats: list[str] | None = None,
) -> Document:
    """Full pipeline: parse, quality-gate, chunk, dedup, build the outputs."""
    if formats is None:
        formats = document.output_formats.split(",")

    try:
        # 1. Parse into structured blocks
        blocks = parse_file(document.filename, file_content)
        if not blocks:
            document.status = "failed"
            document.error_message = "No text content could be extracted from the file"
            await db.commit()
            return document

        text = assessment_text(blocks)

        # 2. Quality gate — a parse that produced garbage never ships
        if settings.quality_gate_enabled:
            report = quality_gate.assess(text)
            if not report.passed:
                document.status = "failed"
                document.error_message = report.summary[:1000]
                await db.commit()
                return document

        lang = detect_language(text)

        # 3. Structure-aware chunking
        drafts = chunk_text(blocks, lang=lang)
        if not drafts:
            document.status = "failed"
            document.error_message = "Text extraction produced no usable chunks"
            await db.commit()
            return document

        # 4. Deduplicate — merge restatements, never merge conflicting facts
        drafts = deduplicate(drafts)

        # 5. Embed the survivors only when the vector output was requested
        embeddings: list[list[float] | None]
        if FORMAT_VECTOR in formats:
            embeddings = await embed_texts([draft.text for draft in drafts])
        else:
            embeddings = [None] * len(drafts)

        # 6. Store chunks (always — keyword search works without embeddings)
        for index, (draft, embedding) in enumerate(zip(drafts, embeddings)):
            db.add(
                Chunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=draft.text,
                    embedding=embedding,
                    page=draft.page,
                    section=draft.section or None,
                    kind=draft.kind,
                    source_doc=draft.source_doc or None,
                    revision=draft.revision or None,
                    provenance=draft.provenance,
                    needs_review=draft.needs_review,
                    lang=draft.lang,
                )
            )

        # 7. Generate downloadable exports for the chosen file formats
        stem = export_stem(document.filename)
        if FORMAT_MARKDOWN in formats:
            md_bytes = build_markdown(document.filename, document.file_type, blocks, drafts).encode("utf-8")
            db.add(
                Artifact(
                    document_id=document.id,
                    format=FORMAT_MARKDOWN,
                    filename=f"{stem}.md",
                    content=md_bytes,
                    size_bytes=len(md_bytes),
                )
            )
        if FORMAT_SQLITE in formats:
            db_bytes = build_sqlite(
                [
                    {
                        "id": document.id,
                        "filename": document.filename,
                        "file_type": document.file_type,
                        "chunks": drafts,
                        "blocks": blocks,
                    }
                ]
            )
            db.add(
                Artifact(
                    document_id=document.id,
                    format=FORMAT_SQLITE,
                    filename=f"{stem}.db",
                    content=db_bytes,
                    size_bytes=len(db_bytes),
                )
            )

        document.status = "ready"
        document.chunk_count = len(drafts)
        await db.commit()

    except Exception as e:
        document.status = "failed"
        document.error_message = str(e)[:1000]
        await db.commit()

    return document
