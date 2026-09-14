"""BEACON V2 — Phase 9 Knowledge RAG Orchestration Service.

Provides the unified high-level service boundary for document ingestion,
security validation, structural extraction, deterministic chunking, SQLite indexing,
and scoped relevance retrieval.
"""

from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional
import uuid

from .chunking import DeterministicChunker
from .extraction import EmptyDocumentError, extract_document_content
from .models import (
    DocumentMetadata,
    DocumentStatus,
    DocumentType,
    KnowledgeChunk,
    KnowledgeContext,
    RetrievalPolicy,
)
from .persistence import KnowledgePersistenceStore, knowledge_persistence
from .retrieval import DeterministicLexicalRetriever, knowledge_retriever
from .security import (
    DEFAULT_KNOWLEDGE_STORAGE_ROOT,
    detect_document_type,
    sanitize_filename,
    validate_file_size,
    validate_path_containment,
)

logger = logging.getLogger("beacon.knowledge.service")


class KnowledgeService:
    """Enterprise knowledge RAG orchestrator for document lifecycle management and grounded retrieval."""

    def __init__(
        self,
        persistence: Optional[KnowledgePersistenceStore] = None,
        retriever: Optional[DeterministicLexicalRetriever] = None,
        storage_root: Optional[Path] = None,
    ):
        self.persistence = persistence or knowledge_persistence
        self.retriever = retriever or (DeterministicLexicalRetriever(persistence=self.persistence) if persistence else knowledge_retriever)
        self.storage_root = (storage_root or DEFAULT_KNOWLEDGE_STORAGE_ROOT).resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def ingest_document(
        self,
        content: bytes,
        filename: str,
        application_id: str = "default_app",
        chunk_size: int = 500,
        chunk_overlap: int = 100,
    ) -> DocumentMetadata:
        """Ingests, validates, stores, extracts, chunks, and indexes a PDF/DOCX company document."""
        # 1. Validate application_id and filename before any filesystem access
        from .security import validate_application_id
        app_id = validate_application_id(application_id if application_id else "default_app")
        safe_fn = sanitize_filename(filename)
        now_str = datetime.now(timezone.utc).isoformat()

        # 2. Security & MIME validation
        validate_file_size(content)
        doc_type = detect_document_type(safe_fn, content)
        content_hash = hashlib.sha256(content).hexdigest()

        # 3. Check for duplicate content in this application scope
        existing_doc = self.persistence.get_document_by_hash(app_id, content_hash)
        if existing_doc and existing_doc.status == DocumentStatus.READY:
            logger.info(
                f"Document with identical content hash '{content_hash[:12]}' already exists in scope '{app_id}'."
            )
            dup_doc = DocumentMetadata(
                document_id=f"doc_{uuid.uuid4().hex[:12]}",
                application_id=app_id,
                filename=safe_fn,
                document_type=doc_type,
                content_hash=content_hash,
                size_bytes=len(content),
                status=DocumentStatus.DUPLICATE,
                page_count=existing_doc.page_count,
                chunk_count=existing_doc.chunk_count,
                storage_path=existing_doc.storage_path,
                created_at=now_str,
                updated_at=now_str,
                metadata={"original_document_id": existing_doc.document_id},
            )
            self.persistence.save_document(dup_doc)
            return dup_doc

        # 4. Construct path and enforce containment BEFORE directory creation
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        app_storage_dir = (self.storage_root / app_id).resolve()
        validate_path_containment(app_storage_dir, self.storage_root)
        app_storage_dir.mkdir(parents=True, exist_ok=True)

        target_file_path = (app_storage_dir / f"{doc_id}_{safe_fn}").resolve()
        validate_path_containment(target_file_path, self.storage_root)

        doc_meta = DocumentMetadata(
            document_id=doc_id,
            application_id=app_id,
            filename=safe_fn,
            document_type=doc_type,
            content_hash=content_hash,
            size_bytes=len(content),
            status=DocumentStatus.PROCESSING,
            storage_path=str(target_file_path),
            created_at=now_str,
            updated_at=now_str,
        )
        self.persistence.save_document(doc_meta)

        try:
            # 5. Save raw file content safely to storage root
            with open(target_file_path, "wb") as f:
                f.write(content)

            # 6. Extract structural text
            extracted = extract_document_content(content, doc_type)
            doc_meta.page_count = extracted.page_count

            # 7. Chunk extracted content deterministically
            chunker = DeterministicChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            chunks = chunker.chunk_document(extracted, doc_meta)

            if not chunks:
                doc_meta.status = DocumentStatus.EMPTY
                doc_meta.error_message = "Document contained zero usable text chunks."
                self.persistence.save_document(doc_meta)
                return doc_meta

            # 8. Persist chunks into SQLite index
            self.persistence.save_chunks(chunks)

            # 9. Mark document as READY
            doc_meta.chunk_count = len(chunks)
            doc_meta.status = DocumentStatus.READY
            doc_meta.updated_at = datetime.now(timezone.utc).isoformat()
            self.persistence.save_document(doc_meta)

            logger.info(
                f"Successfully ingested and indexed document '{doc_id}' ({safe_fn}) with {len(chunks)} chunks."
            )
            return doc_meta

        except EmptyDocumentError as empty_exc:
            logger.warning(f"Empty document detected '{doc_id}': {empty_exc}")
            doc_meta.status = DocumentStatus.EMPTY
            doc_meta.error_message = str(empty_exc)
            doc_meta.updated_at = datetime.now(timezone.utc).isoformat()
            self.persistence.save_document(doc_meta)
            return doc_meta

        except Exception as exc:
            logger.error(f"Error processing document '{doc_id}': {exc}", exc_info=True)
            doc_meta.status = DocumentStatus.ERROR
            doc_meta.error_message = "Document extraction or indexing failed."
            doc_meta.updated_at = datetime.now(timezone.utc).isoformat()
            self.persistence.save_document(doc_meta)
            return doc_meta

    def list_documents(self, application_id: Optional[str] = None) -> list[DocumentMetadata]:
        """Lists all ingested documents, optionally filtered by application scope."""
        if application_id:
            from .security import validate_application_id
            application_id = validate_application_id(application_id)
        return self.persistence.list_documents(application_id=application_id)

    def get_document(self, document_id: str) -> Optional[DocumentMetadata]:
        """Retrieves metadata for a specific document ID."""
        return self.persistence.get_document(document_id)

    def list_chunks(self, document_id: str) -> list[KnowledgeChunk]:
        """Retrieves all indexed chunks for a document ID."""
        return self.persistence.list_chunks_for_document(document_id)

    def delete_document(self, document_id: str) -> bool:
        """Safely removes document, associated chunks, and raw stored file from storage."""
        doc = self.persistence.get_document(document_id)
        if not doc:
            return False

        # Attempt to delete file from disk if present
        if doc.storage_path and os.path.exists(doc.storage_path):
            try:
                os.remove(doc.storage_path)
            except Exception as e:
                logger.error(f"Could not remove physical file '{doc.storage_path}': {e}", exc_info=True)
                raise IOError(f"Could not remove physical storage file for document '{document_id}'") from e

        return self.persistence.delete_document(document_id)

    def retrieve(
        self,
        query: str,
        application_id: str,
        top_k: int = 5,
        min_relevance_score: float = 0.01,
        policy: Optional[RetrievalPolicy] = None,
    ) -> KnowledgeContext:
        """Executes scoped lexical retrieval and returns a grounded KnowledgeContext package."""
        from .security import validate_application_id
        valid_app_id = validate_application_id(application_id)
        return self.retriever.retrieve(
            query=query,
            application_id=valid_app_id,
            top_k=top_k,
            min_relevance_score=min_relevance_score,
            policy=policy,
        )


knowledge_service = KnowledgeService()
