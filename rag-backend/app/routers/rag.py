"""RAG query API endpoints"""

import uuid
import time
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.database import get_db
from app.models.database import OEM, AuditAction
from app.models.schemas import RAGQueryRequest, RAGQueryResponse, SourceDocument
from app.dependencies import get_current_oem, get_client_ip
from app.services.embeddings import embeddings_service
from app.services.vector_db import vector_db
from app.services.llm import llm_service
from app.services.security import audit_logger

router = APIRouter(prefix="/query", tags=["RAG Queries"])
logger = structlog.get_logger(__name__)


@router.post("/", response_model=RAGQueryResponse)
async def query_knowledge_base(
    query_request: RAGQueryRequest,
    current_oem: OEM = Depends(get_current_oem),
    db: AsyncSession = Depends(get_db),
    ip_address: str = Depends(get_client_ip)
):
    """
    Query the knowledge base using RAG (Retrieval-Augmented Generation)

    Process:
    1. Generate query embedding
    2. Retrieve relevant context from vector DB
    3. Send context + question to LLM
    4. Return answer with source citations
    """
    start_time = time.time()
    query_id = str(uuid.uuid4())

    try:
        # Generate query embedding
        query_embedding = embeddings_service.encode_text(query_request.question)

        # Search vector database for similar chunks
        similar_chunks = await vector_db.search_similar(
            collection_name=current_oem.collection_name,
            query_embedding=query_embedding,
            top_k=query_request.max_sources,
            equipment_model=query_request.equipment_model
        )

        if not similar_chunks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No relevant information found in knowledge base"
            )

        # Generate answer using LLM
        llm_result = await llm_service.generate_answer(
            question=query_request.question,
            context_chunks=similar_chunks,
            equipment_model=query_request.equipment_model,
            temperature=query_request.temperature,
            max_tokens=query_request.max_tokens
        )

        # Format source documents
        sources: List[SourceDocument] = []
        if query_request.include_sources:
            for chunk in similar_chunks:
                sources.append(SourceDocument(
                    document_id=chunk["document_id"],
                    document_title=chunk.get("document_title", "Unknown"),
                    chunk_index=chunk["chunk_index"],
                    page_number=chunk.get("page_number") if chunk.get("page_number", 0) > 0 else None,
                    section_title=chunk.get("section_title") or None,
                    content_snippet=chunk["content"][:200] + "..." if len(chunk["content"]) > 200 else chunk["content"],
                    relevance_score=chunk["score"]
                ))

        # Calculate processing time
        processing_time_ms = int((time.time() - start_time) * 1000)

        # Prepare response
        response = RAGQueryResponse(
            answer=llm_result["answer"],
            sources=sources,
            confidence=llm_result["confidence"],
            query_id=query_id,
            processing_time_ms=processing_time_ms
        )

        # Audit log
        await audit_logger.log_action(
            action=AuditAction.QUERY_EXECUTED.value,
            oem_id=current_oem.id,
            resource_type="query",
            resource_id=query_id,
            ip_address=ip_address,
            details={
                "question_length": len(query_request.question),
                "sources_count": len(sources),
                "confidence": llm_result["confidence"],
                "processing_time_ms": processing_time_ms,
                "equipment_model": query_request.equipment_model
            }
        )

        logger.info(
            "Query executed",
            oem_id=current_oem.id,
            query_id=query_id,
            sources=len(sources),
            confidence=llm_result["confidence"],
            time_ms=processing_time_ms
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Query failed", query_id=query_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process query: {str(e)}"
        )


@router.post("/vision", response_model=RAGQueryResponse)
async def query_with_vision(
    query_request: RAGQueryRequest,
    current_oem: OEM = Depends(get_current_oem),
    db: AsyncSession = Depends(get_db),
    ip_address: str = Depends(get_client_ip)
):
    """
    Query with vision capabilities (for image-based questions)

    Combines image analysis with knowledge base retrieval
    """
    start_time = time.time()
    query_id = str(uuid.uuid4())

    try:
        if not query_request.image_base64:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image is required for vision queries"
            )

        # Generate query embedding from text question
        query_embedding = embeddings_service.encode_text(
            query_request.image_context or query_request.question
        )

        # Search vector database
        similar_chunks = await vector_db.search_similar(
            collection_name=current_oem.collection_name,
            query_embedding=query_embedding,
            top_k=query_request.max_sources,
            equipment_model=query_request.equipment_model
        )

        # Generate answer with vision
        llm_result = await llm_service.generate_with_vision(
            question=query_request.question,
            image_base64=query_request.image_base64,
            context_chunks=similar_chunks,
            equipment_model=query_request.equipment_model,
            temperature=query_request.temperature,
            max_tokens=query_request.max_tokens
        )

        # Format sources
        sources: List[SourceDocument] = []
        if query_request.include_sources and similar_chunks:
            for chunk in similar_chunks:
                sources.append(SourceDocument(
                    document_id=chunk["document_id"],
                    document_title=chunk.get("document_title", "Unknown"),
                    chunk_index=chunk["chunk_index"],
                    page_number=chunk.get("page_number") if chunk.get("page_number", 0) > 0 else None,
                    section_title=chunk.get("section_title") or None,
                    content_snippet=chunk["content"][:200] + "...",
                    relevance_score=chunk["score"]
                ))

        processing_time_ms = int((time.time() - start_time) * 1000)

        # Prepare response
        response = RAGQueryResponse(
            answer=llm_result.get("voice_instruction", ""),
            sources=sources,
            confidence=0.8,  # Default for vision queries
            query_id=query_id,
            processing_time_ms=processing_time_ms,
            status=llm_result.get("status"),
            voice_instruction=llm_result.get("voice_instruction"),
            reasoning=llm_result.get("reasoning")
        )

        # Audit log
        await audit_logger.log_action(
            action=AuditAction.QUERY_EXECUTED.value,
            oem_id=current_oem.id,
            resource_type="vision_query",
            resource_id=query_id,
            ip_address=ip_address,
            details={
                "has_image": True,
                "status": llm_result.get("status"),
                "processing_time_ms": processing_time_ms
            }
        )

        logger.info(
            "Vision query executed",
            oem_id=current_oem.id,
            query_id=query_id,
            status=llm_result.get("status"),
            time_ms=processing_time_ms
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Vision query failed", query_id=query_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process vision query: {str(e)}"
        )
