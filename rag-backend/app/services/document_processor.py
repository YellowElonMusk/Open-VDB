"""Document processing service for chunking and ingestion"""

import re
import hashlib
from typing import List, Dict, Any, Tuple
from pathlib import Path
import structlog

# Document parsers
import pypdf
from docx import Document as DocxDocument
import markdown

from app.config import settings
from app.services.embeddings import embeddings_service

logger = structlog.get_logger(__name__)


class DocumentProcessor:
    """Process documents: extract text, chunk, and prepare for embedding"""

    def __init__(self):
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap

    async def extract_text(self, file_path: str, file_type: str) -> Tuple[str, Dict[str, Any]]:
        """
        Extract text from various file formats

        Args:
            file_path: Path to file
            file_type: File extension (.pdf, .txt, .docx, .md)

        Returns:
            Tuple of (extracted_text, metadata)
        """
        try:
            if file_type == ".pdf":
                return await self._extract_pdf(file_path)
            elif file_type == ".txt":
                return await self._extract_txt(file_path)
            elif file_type == ".docx":
                return await self._extract_docx(file_path)
            elif file_type == ".md":
                return await self._extract_markdown(file_path)
            else:
                raise ValueError(f"Unsupported file type: {file_type}")

        except Exception as e:
            logger.error("Failed to extract text", file_path=file_path, error=str(e))
            raise

    async def _extract_pdf(self, file_path: str) -> Tuple[str, Dict[str, Any]]:
        """Extract text from PDF"""
        text_parts = []
        metadata = {"pages": [], "total_pages": 0}

        with open(file_path, "rb") as f:
            pdf_reader = pypdf.PdfReader(f)
            metadata["total_pages"] = len(pdf_reader.pages)

            for page_num, page in enumerate(pdf_reader.pages, start=1):
                page_text = page.extract_text()
                if page_text.strip():
                    text_parts.append(page_text)
                    metadata["pages"].append({
                        "page": page_num,
                        "char_count": len(page_text)
                    })

        full_text = "\n\n".join(text_parts)
        return full_text, metadata

    async def _extract_txt(self, file_path: str) -> Tuple[str, Dict[str, Any]]:
        """Extract text from plain text file"""
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

        metadata = {"char_count": len(text)}
        return text, metadata

    async def _extract_docx(self, file_path: str) -> Tuple[str, Dict[str, Any]]:
        """Extract text from DOCX"""
        doc = DocxDocument(file_path)
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
        text = "\n\n".join(paragraphs)

        metadata = {
            "paragraphs": len(paragraphs),
            "char_count": len(text)
        }
        return text, metadata

    async def _extract_markdown(self, file_path: str) -> Tuple[str, Dict[str, Any]]:
        """Extract text from Markdown (keep as plain text)"""
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            md_text = f.read()

        # Convert to HTML then strip tags for plain text
        html = markdown.markdown(md_text)
        text = re.sub(r"<[^>]+>", "", html)

        metadata = {"char_count": len(text)}
        return text, metadata

    def chunk_text(
        self,
        text: str,
        metadata: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Split text into overlapping chunks

        Args:
            text: Full document text
            metadata: Optional metadata to attach to chunks

        Returns:
            List of chunk dictionaries
        """
        if metadata is None:
            metadata = {}

        # Clean text
        text = self._clean_text(text)

        # Split into sentences (approximate)
        sentences = self._split_sentences(text)

        chunks = []
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sentence_length = len(sentence)

            # If adding this sentence exceeds chunk size, save current chunk
            if current_length + sentence_length > self.chunk_size and current_chunk:
                chunk_text = " ".join(current_chunk)
                chunks.append({
                    "content": chunk_text,
                    "char_count": len(chunk_text),
                    "metadata": metadata.copy()
                })

                # Keep last few sentences for overlap
                overlap_text = chunk_text[-self.chunk_overlap:]
                overlap_sentences = self._split_sentences(overlap_text)
                current_chunk = overlap_sentences
                current_length = sum(len(s) for s in current_chunk)

            current_chunk.append(sentence)
            current_length += sentence_length

        # Add final chunk
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append({
                "content": chunk_text,
                "char_count": len(chunk_text),
                "metadata": metadata.copy()
            })

        # Add chunk indices
        for i, chunk in enumerate(chunks):
            chunk["chunk_index"] = i

        logger.info("Chunked text", total_chunks=len(chunks))
        return chunks

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
        return text.strip()

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences (simple heuristic)"""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]

    async def process_chunks(
        self,
        chunks: List[Dict[str, Any]],
        document_id: str,
        document_metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Process chunks: generate embeddings and prepare for vector DB

        Args:
            chunks: List of text chunks
            document_id: Document UUID
            document_metadata: Metadata to attach

        Returns:
            List of processed chunks with embeddings
        """
        try:
            texts = [chunk["content"] for chunk in chunks]

            # Generate embeddings in batch
            embeddings = embeddings_service.encode_batch(texts)

            processed_chunks = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                chunk_id = self._generate_chunk_id(document_id, i)

                processed_chunk = {
                    "id": chunk_id,
                    "document_id": document_id,
                    "chunk_index": i,
                    "content": chunk["content"],
                    "embedding": embedding,
                    "content_hash": self._hash_content(chunk["content"]),
                    "token_count": self._estimate_tokens(chunk["content"]),
                    "page_number": chunk.get("page_number", 0),
                    "section_title": chunk.get("section_title", ""),
                    "equipment_model": document_metadata.get("equipment_model", ""),
                    "document_title": document_metadata.get("title", ""),
                }

                processed_chunks.append(processed_chunk)

            logger.info(
                "Processed chunks with embeddings",
                document_id=document_id,
                count=len(processed_chunks)
            )

            return processed_chunks

        except Exception as e:
            logger.error(
                "Failed to process chunks",
                document_id=document_id,
                error=str(e)
            )
            raise

    def _generate_chunk_id(self, document_id: str, chunk_index: int) -> str:
        """Generate deterministic chunk ID"""
        content = f"{document_id}:{chunk_index}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _hash_content(self, content: str) -> str:
        """Generate SHA-256 hash of content"""
        return hashlib.sha256(content.encode()).hexdigest()

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough approximation)"""
        return len(text) // 4

    async def extract_metadata_from_content(self, text: str) -> Dict[str, Any]:
        """
        Extract metadata from document content (title, sections, etc.)

        Args:
            text: Document text

        Returns:
            Extracted metadata
        """
        metadata = {}

        # Try to extract title (first line or heading)
        lines = text.split("\n")
        for line in lines[:5]:
            line = line.strip()
            if line and len(line) < 200:
                metadata["auto_title"] = line
                break

        # Extract potential section headers
        sections = re.findall(r"^#+\s+(.+)$", text, re.MULTILINE)
        if sections:
            metadata["sections"] = sections[:10]  # First 10 sections

        return metadata


# Global instance
document_processor = DocumentProcessor()
