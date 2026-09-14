"""BEACON V2 — Phase 9 Knowledge RAG REST API Router.

Exposes REST endpoints for uploading and indexing company documents (PDF/DOCX),
querying document metadata, deleting documents, and executing scoped lexical retrieval.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from auth import User, get_current_active_user
from knowledge.models import (
    DocumentMetadata,
    KnowledgeChunk,
    KnowledgeContext,
    KnowledgeQuery,
)
from knowledge.security import (
    FileSizeLimitExceededError,
    InvalidFileSignatureError,
    KnowledgeSecurityError,
    PathTraversalError,
)
from knowledge.service import knowledge_service

logger = logging.getLogger("beacon.api.knowledge")

knowledge_router = APIRouter(tags=["v2-company-knowledge-rag"])


@knowledge_router.post(
    "/api/v2/knowledge/documents/upload",
    response_model=DocumentMetadata,
    status_code=status.HTTP_200_OK,
)
async def upload_document(
    file: UploadFile = File(...),
    application_id: str = Form("default_app"),
    chunk_size: int = Form(500),
    chunk_overlap: int = Form(100),
    current_user: Optional[User] = Depends(get_current_active_user),
) -> DocumentMetadata:
    """Uploads and indexes a PDF or DOCX enterprise knowledge document."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file must have a valid filename.")

    try:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file payload is empty.")

        doc_meta = knowledge_service.ingest_document(
            content=content,
            filename=file.filename,
            application_id=application_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return doc_meta

    except FileSizeLimitExceededError as size_exc:
        logger.warning(f"File size limit exceeded for upload '{file.filename}': {size_exc}")
        raise HTTPException(status_code=413, detail=str(size_exc))
    except (InvalidFileSignatureError, PathTraversalError, KnowledgeSecurityError) as sec_exc:
        logger.warning(f"Security validation failed for upload '{file.filename}': {sec_exc}")
        raise HTTPException(status_code=400, detail=str(sec_exc))
    except Exception as exc:
        logger.error(f"Unexpected error uploading document '{file.filename}': {exc}")
        raise HTTPException(status_code=500, detail=f"Document ingestion failed: {exc}")


@knowledge_router.get(
    "/api/v2/knowledge/documents",
    response_model=list[DocumentMetadata],
    status_code=status.HTTP_200_OK,
)
def list_documents(
    application_id: Optional[str] = Query(None, description="Filter documents by application scope"),
    current_user: Optional[User] = Depends(get_current_active_user),
) -> list[DocumentMetadata]:
    """Lists ingested knowledge documents, optionally filtered by application scope."""
    try:
        return knowledge_service.list_documents(application_id=application_id)
    except Exception as exc:
        logger.error(f"Error listing documents: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@knowledge_router.get(
    "/api/v2/knowledge/documents/{document_id}",
    response_model=DocumentMetadata,
    status_code=status.HTTP_200_OK,
)
def get_document(
    document_id: str,
    current_user: Optional[User] = Depends(get_current_active_user),
) -> DocumentMetadata:
    """Retrieves metadata for a specific knowledge document."""
    doc = knowledge_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Knowledge document '{document_id}' not found.")
    return doc


@knowledge_router.get(
    "/api/v2/knowledge/documents/{document_id}/chunks",
    response_model=list[KnowledgeChunk],
    status_code=status.HTTP_200_OK,
)
def get_document_chunks(
    document_id: str,
    current_user: Optional[User] = Depends(get_current_active_user),
) -> list[KnowledgeChunk]:
    """Retrieves all indexed chunks for a specific knowledge document."""
    doc = knowledge_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Knowledge document '{document_id}' not found.")
    return knowledge_service.list_chunks(document_id)


@knowledge_router.delete(
    "/api/v2/knowledge/documents/{document_id}",
    status_code=status.HTTP_200_OK,
)
def delete_document(
    document_id: str,
    current_user: Optional[User] = Depends(get_current_active_user),
) -> dict:
    """Safely deletes an ingested knowledge document and its associated chunk index."""
    deleted = knowledge_service.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Knowledge document '{document_id}' not found.")
    return {"deleted": True, "document_id": document_id}


@knowledge_router.post(
    "/api/v2/knowledge/retrieve",
    response_model=KnowledgeContext,
    status_code=status.HTTP_200_OK,
)
def retrieve_knowledge(
    req: KnowledgeQuery,
    current_user: Optional[User] = Depends(get_current_active_user),
) -> KnowledgeContext:
    """Executes deterministic scoped lexical retrieval against the enterprise knowledge index."""
    try:
        context = knowledge_service.retrieve(
            query=req.query,
            application_id=req.application_id,
            top_k=req.top_k,
            min_relevance_score=req.min_relevance_score,
            policy=req.policy,
        )
        return context
    except Exception as exc:
        logger.error(f"Error retrieving knowledge for query '{req.query}': {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
