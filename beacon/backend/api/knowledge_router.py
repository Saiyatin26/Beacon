"""BEACON V2 — Phase 9 Knowledge RAG REST API Router.

Exposes REST endpoints for uploading and indexing company documents (PDF/DOCX),
querying document metadata, deleting documents, and executing scoped lexical retrieval
with authoritative RBAC project authorization and safe error handling.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from auth import (
    Permission,
    User,
    auth_repository,
    get_current_active_user,
    verify_user_project_permission,
)
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
    validate_application_id,
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
    current_user: User = Depends(get_current_active_user),
) -> DocumentMetadata:
    """Uploads and indexes a PDF or DOCX enterprise knowledge document."""
    # 1. Validate application scope identifier
    try:
        valid_app_id = validate_application_id(application_id)
    except PathTraversalError as path_err:
        logger.warning(f"Invalid application identifier on upload: {path_err}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid application identifier.")

    # 2. Authorize user against target application/project scope
    verify_user_project_permission(current_user, valid_app_id, Permission.CERTIFY)

    # 3. Validate file payload
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file must have a valid filename.")

    try:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file payload is empty.")

        doc_meta = knowledge_service.ingest_document(
            content=content,
            filename=file.filename,
            application_id=valid_app_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return doc_meta

    except FileSizeLimitExceededError as size_exc:
        logger.warning(f"File size limit exceeded for upload '{file.filename}': {size_exc}")
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Document exceeds maximum allowed file size.")
    except (InvalidFileSignatureError, PathTraversalError, KnowledgeSecurityError) as sec_exc:
        logger.warning(f"Security validation failed for upload '{file.filename}': {sec_exc}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(sec_exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Unexpected diagnostic error uploading document '{file.filename}' for app '{valid_app_id}': {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Document ingestion failed.")


@knowledge_router.get(
    "/api/v2/knowledge/documents",
    response_model=list[DocumentMetadata],
    status_code=status.HTTP_200_OK,
)
def list_documents(
    application_id: Optional[str] = Query(None, description="Filter documents by application scope"),
    current_user: User = Depends(get_current_active_user),
) -> list[DocumentMetadata]:
    """Lists ingested knowledge documents, strictly authorized by application scope."""
    try:
        if application_id:
            valid_app_id = validate_application_id(application_id)
            verify_user_project_permission(current_user, valid_app_id, Permission.VIEW)
            return knowledge_service.list_documents(application_id=valid_app_id)
        else:
            if current_user.is_system_admin:
                return knowledge_service.list_documents(application_id=None)
            
            # Non-admin user: list only documents from projects where user has memberships
            memberships = auth_repository.get_user_memberships(current_user.user_id)
            accessible_pids = {m.project_id for m in memberships}
            accessible_pids.update({m.project_id.replace("benchmark_", "") for m in memberships if m.project_id.startswith("benchmark_")})
            all_docs = knowledge_service.list_documents(application_id=None)
            return [doc for doc in all_docs if doc.application_id in accessible_pids]

    except PathTraversalError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid application identifier.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Diagnostic error listing knowledge documents: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list knowledge documents.")


@knowledge_router.get(
    "/api/v2/knowledge/documents/{document_id}",
    response_model=DocumentMetadata,
    status_code=status.HTTP_200_OK,
)
def get_document(
    document_id: str,
    current_user: User = Depends(get_current_active_user),
) -> DocumentMetadata:
    """Retrieves metadata for a specific knowledge document with project authorization check."""
    doc = knowledge_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Knowledge document '{document_id}' not found.")
    
    verify_user_project_permission(current_user, doc.application_id, Permission.VIEW)
    return doc


@knowledge_router.get(
    "/api/v2/knowledge/documents/{document_id}/chunks",
    response_model=list[KnowledgeChunk],
    status_code=status.HTTP_200_OK,
)
def get_document_chunks(
    document_id: str,
    current_user: User = Depends(get_current_active_user),
) -> list[KnowledgeChunk]:
    """Retrieves all indexed chunks for a specific knowledge document with authorization check."""
    doc = knowledge_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Knowledge document '{document_id}' not found.")
    
    verify_user_project_permission(current_user, doc.application_id, Permission.VIEW)
    return knowledge_service.list_chunks(document_id)


@knowledge_router.delete(
    "/api/v2/knowledge/documents/{document_id}",
    status_code=status.HTTP_200_OK,
)
def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Safely deletes an ingested knowledge document, physical file, and associated chunk index."""
    doc = knowledge_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Knowledge document '{document_id}' not found.")
    
    verify_user_project_permission(current_user, doc.application_id, Permission.CERTIFY)

    try:
        deleted = knowledge_service.delete_document(document_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Knowledge document '{document_id}' not found.")
        return {"deleted": True, "document_id": document_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Diagnostic error deleting document '{document_id}': {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete knowledge document.")


@knowledge_router.post(
    "/api/v2/knowledge/retrieve",
    response_model=KnowledgeContext,
    status_code=status.HTTP_200_OK,
)
def retrieve_knowledge(
    req: KnowledgeQuery,
    current_user: User = Depends(get_current_active_user),
) -> KnowledgeContext:
    """Executes deterministic scoped lexical retrieval against the enterprise knowledge index."""
    try:
        valid_app_id = validate_application_id(req.application_id)
    except PathTraversalError as path_err:
        logger.warning(f"Invalid application identifier on retrieval: {path_err}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid application identifier.")

    verify_user_project_permission(current_user, valid_app_id, Permission.VIEW)

    try:
        context = knowledge_service.retrieve(
            query=req.query,
            application_id=valid_app_id,
            top_k=req.top_k,
            min_relevance_score=req.min_relevance_score,
            policy=req.policy,
        )
        return context
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Diagnostic error retrieving knowledge for query '{req.query}' in app '{valid_app_id}': {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Knowledge retrieval failed.")

