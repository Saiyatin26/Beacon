"""BEACON V2 — Phase 9 Knowledge Retrieval & RAG Domain Models.

Defines core data models for ingested company documents (PDF/DOCX),
extracted structural text, deterministic knowledge chunks, retrieval policies,
and grounded knowledge context packages.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class DocumentType(str, Enum):
    """Supported document formats for enterprise knowledge ingestion."""
    PDF = "PDF"
    DOCX = "DOCX"


class DocumentStatus(str, Enum):
    """Lifecycle and indexing readiness state of an ingested knowledge document."""
    UPLOADED = "UPLOADED"      # Uploaded to temporary/storage staging
    PROCESSING = "PROCESSING"  # Parsing, extraction, and chunking in progress
    READY = "READY"            # Extracted, chunked, and searchable in index
    EMPTY = "EMPTY"            # Document contained no meaningful extractable text
    DUPLICATE = "DUPLICATE"    # Exact content hash already indexed in scope
    ERROR = "ERROR"            # Extraction or indexing encountered fatal error
    REJECTED = "REJECTED"      # Rejected by security or validation rules


class RetrievalStatus(str, Enum):
    """Status classification of a knowledge retrieval query execution."""
    SUCCESS_WITH_RESULTS = "SUCCESS_WITH_RESULTS"
    SUCCESS_NO_RESULTS = "SUCCESS_NO_RESULTS"
    ERROR = "ERROR"


def compute_deterministic_hash(data: Any) -> str:
    """Computes a deterministic SHA-256 digest of arbitrary structured data or text."""
    if isinstance(data, (dict, list)):
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    elif isinstance(data, str):
        canonical = data
    elif isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    else:
        canonical = str(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DocumentPage(BaseModel):
    """Extracted text and metadata for a single document page."""
    model_config = ConfigDict(extra="ignore")

    page_number: int
    text: str
    character_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentSection(BaseModel):
    """Structural section or heading boundary extracted from structured documents."""
    model_config = ConfigDict(extra="ignore")

    heading: str
    level: int = 1
    text: str
    page_number: Optional[int] = None


class ExtractedDocument(BaseModel):
    """Normalized structured text payload resulting from document extraction."""
    model_config = ConfigDict(extra="ignore")

    raw_text: str
    normalized_text: str
    page_count: int = 0
    pages: list[DocumentPage] = Field(default_factory=list)
    sections: list[DocumentSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkMetadata(BaseModel):
    """Comprehensive provenance and structural metadata for a knowledge chunk."""
    model_config = ConfigDict(extra="ignore")

    document_id: str
    application_id: str
    filename: str
    document_type: DocumentType
    content_hash: str
    chunk_index: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    heading: Optional[str] = None
    section: Optional[str] = None
    character_start: int = 0
    character_end: int = 0
    custom_metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeChunk(BaseModel):
    """Deterministic granular knowledge chunk indexed for scoped retrieval."""
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    document_id: str
    application_id: str
    chunk_index: int
    text: str
    metadata: ChunkMetadata
    fingerprint: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_fingerprint(self) -> str:
        """Computes deterministic SHA-256 fingerprint over semantic chunk content & position."""
        payload = {
            "document_id": self.document_id,
            "application_id": self.application_id,
            "chunk_index": self.chunk_index,
            "text": self.text.strip(),
            "content_hash": self.metadata.content_hash,
        }
        return compute_deterministic_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", self.compute_fingerprint())


class DocumentMetadata(BaseModel):
    """Persistent lifecycle record for an ingested knowledge document."""
    model_config = ConfigDict(extra="ignore")

    document_id: str
    application_id: str
    filename: str
    document_type: DocumentType
    content_hash: str
    size_bytes: int
    status: DocumentStatus = DocumentStatus.UPLOADED
    page_count: int = 0
    chunk_count: int = 0
    storage_path: str = ""
    error_message: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalPolicy(BaseModel):
    """Configuration governing knowledge query retrieval boundaries and relevance."""
    model_config = ConfigDict(extra="ignore")

    top_k: int = Field(default=5, ge=1, le=50)
    min_relevance_score: float = Field(default=0.01, ge=0.0, le=1.0)
    include_full_metadata: bool = True
    retrieval_strategy: str = "LEXICAL_BM25"


class RetrievedChunk(BaseModel):
    """Single matching knowledge chunk with relevance score and complete provenance."""
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    document_id: str
    application_id: str
    filename: str
    text: str
    relevance_score: float
    chunk_index: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    heading: Optional[str] = None
    section: Optional[str] = None
    content_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeQuery(BaseModel):
    """Payload for querying the scoped company knowledge retrieval index."""
    model_config = ConfigDict(extra="ignore")

    application_id: str
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    min_relevance_score: float = Field(default=0.01, ge=0.0, le=1.0)
    policy: Optional[RetrievalPolicy] = None


class KnowledgeContext(BaseModel):
    """Grounded knowledge context container returned for Phase 10 explanation consumption."""
    model_config = ConfigDict(extra="ignore")

    query: str
    application_id: str
    status: RetrievalStatus = RetrievalStatus.SUCCESS_NO_RESULTS
    policy: Optional[RetrievalPolicy] = None
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    total_chunks_evaluated: int = 0
    sources: list[str] = Field(default_factory=list)  # Unique source filenames
    document_ids: list[str] = Field(default_factory=list)  # Unique document IDs
    retrieval_fingerprint: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    summary: dict[str, Any] = Field(default_factory=dict)

    def compute_retrieval_fingerprint(self) -> str:
        """Computes deterministic SHA-256 fingerprint over query, scope, policy, and ordered matched chunks."""
        ordered_chunk_ids = [
            {
                "chunk_id": c.chunk_id,
                "score": round(c.relevance_score, 6),
                "doc_id": c.document_id,
                "content_hash": c.content_hash,
            }
            for c in self.retrieved_chunks
        ]
        policy_data = {
            "top_k": self.policy.top_k if self.policy else 5,
            "min_relevance_score": round(self.policy.min_relevance_score, 4) if self.policy else 0.01,
            "retrieval_strategy": self.policy.retrieval_strategy if self.policy else "LEXICAL_BM25",
        }
        payload = {
            "query": self.query.strip(),
            "application_id": self.application_id,
            "status": self.status.value,
            "policy": policy_data,
            "chunks": ordered_chunk_ids,
        }
        return compute_deterministic_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.retrieval_fingerprint:
            object.__setattr__(self, "retrieval_fingerprint", self.compute_retrieval_fingerprint())
