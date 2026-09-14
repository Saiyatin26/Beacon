"""BEACON V2 — Knowledge Retrieval & RAG Legacy Compatibility Boundary.

NOTE: This module is retained for backward compatibility with early Phase 1 stub tests.
The authoritative, canonical Phase 9 data contracts are defined in `knowledge.models`.
Do not introduce new code against these legacy classes; use `knowledge.models` directly.
"""

from abc import ABC, abstractmethod
import hashlib
import warnings
from typing import Any, Optional
from pydantic import BaseModel, Field

# Re-export canonical Phase 9 types
from .models import (
    ChunkMetadata,
    DocumentMetadata as CanonicalDocumentMetadata,
    DocumentStatus,
    DocumentType,
    KnowledgeChunk as CanonicalKnowledgeChunk,
    KnowledgeContext as CanonicalKnowledgeContext,
    KnowledgeQuery as CanonicalKnowledgeQuery,
    RetrievalPolicy,
    RetrievalStatus,
    RetrievedChunk,
)


class KnowledgeSource(BaseModel):
    """Specification of an external knowledge source repository or document set."""
    source_id: str
    name: str
    source_type: str = "document"  # "document", "wiki", "code_repo", "spec"
    uri: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDocument(BaseModel):
    """Legacy model for ingested documents (deprecated, use DocumentMetadata)."""
    doc_id: str
    source_id: str
    title: str
    content: str = ""
    doc_type: str = "pdf"  # "pdf", "docx"
    doc_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.doc_hash and self.content:
            object.__setattr__(self, "doc_hash", hashlib.sha256(self.content.encode("utf-8")).hexdigest())


class KnowledgeChunk(BaseModel):
    """Legacy chunk model (deprecated, use knowledge.models.KnowledgeChunk)."""
    chunk_id: str
    doc_id: str
    text: str
    chunk_index: int = 0
    embedding_id: Optional[str] = None
    relevance_score: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeContext(BaseModel):
    """Legacy context container (deprecated, use knowledge.models.KnowledgeContext)."""
    query: str
    chunks: list[KnowledgeChunk] = Field(default_factory=list)
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeRetriever(ABC):
    """Abstract interface for knowledge retrieval engines."""

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> KnowledgeContext:
        """Retrieves relevant knowledge chunks for a query."""
        pass


class StubKnowledgeRetriever(KnowledgeRetriever):
    """Deterministic stub retriever for Phase 1 testing and offline usage."""

    def retrieve(self, query: str, top_k: int = 5) -> KnowledgeContext:
        return KnowledgeContext(
            query=query,
            chunks=[],
            confidence=1.0,
            metadata={"retriever": "stub_phase1"},
        )

