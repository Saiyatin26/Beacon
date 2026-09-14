"""BEACON V2 — Phase 9 Knowledge Retrieval & RAG Package.

Provides modular, optional enterprise knowledge ingestion and deterministic
lexical retrieval for PDF and DOCX company documentation.
"""

from .models import (
    ChunkMetadata,
    DocumentMetadata,
    DocumentPage,
    DocumentSection,
    DocumentStatus,
    DocumentType,
    ExtractedDocument,
    KnowledgeChunk,
    KnowledgeContext,
    KnowledgeQuery,
    RetrievalPolicy,
    RetrievalStatus,
    RetrievedChunk,
)
from .security import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_MAX_FILE_SIZE_MB,
    FileSizeLimitExceededError,
    InvalidFileSignatureError,
    KnowledgeSecurityError,
    PathTraversalError,
    detect_document_type,
    sanitize_filename,
    validate_application_id,
    validate_file_size,
    validate_path_containment,
)
from .chunking import DeterministicChunker
from .extraction import (
    DOCXExtractor,
    DocumentExtractionError,
    EmptyDocumentError,
    PDFExtractor,
    TextNormalizer,
    extract_document_content,
)
from .persistence import KnowledgePersistenceStore, knowledge_persistence
from .retrieval import DeterministicLexicalRetriever, knowledge_retriever
from .service import KnowledgeService, knowledge_service

__all__ = [
    "ChunkMetadata",
    "DocumentMetadata",
    "DocumentPage",
    "DocumentSection",
    "DocumentStatus",
    "DocumentType",
    "ExtractedDocument",
    "KnowledgeChunk",
    "KnowledgeContext",
    "KnowledgeQuery",
    "RetrievalPolicy",
    "RetrievalStatus",
    "RetrievedChunk",
    "KnowledgeSecurityError",
    "PathTraversalError",
    "FileSizeLimitExceededError",
    "InvalidFileSignatureError",
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "DEFAULT_MAX_FILE_SIZE_MB",
    "detect_document_type",
    "sanitize_filename",
    "validate_application_id",
    "validate_file_size",
    "validate_path_containment",
    "DeterministicChunker",
    "DocumentExtractionError",
    "EmptyDocumentError",
    "PDFExtractor",
    "DOCXExtractor",
    "TextNormalizer",
    "extract_document_content",
    "KnowledgePersistenceStore",
    "knowledge_persistence",
    "DeterministicLexicalRetriever",
    "knowledge_retriever",
    "KnowledgeService",
    "knowledge_service",
]
