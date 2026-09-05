"""BEACON V2 — Knowledge Retrieval & RAG Extension Boundary Contracts.

Defines the clean boundary contracts for future knowledge ingestion and RAG retrieval
(supporting future company documentation, specifications, and business rules).
Actual vector databases, embeddings, and document parsers are deliberately deferred to later phases.
"""

from abc import ABC, abstractmethod
import hashlib
from typing import Any, Optional
from pydantic import BaseModel, Field


class KnowledgeSource(BaseModel):
    """Specification of an external knowledge source repository or document set."""
    source_id: str
    name: str
    source_type: str = "document"  # "document", "wiki", "code_repo", "spec"
    uri: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDocument(BaseModel):
    """A single ingested document representing enterprise domain knowledge."""
    doc_id: str
    source_id: str
    title: str
    content: str = ""
    doc_type: str = "text"  # "text", "markdown", "pdf", "docx"
    doc_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.doc_hash and self.content:
            object.__setattr__(self, "doc_hash", hashlib.sha256(self.content.encode("utf-8")).hexdigest())


class KnowledgeChunk(BaseModel):
    """A granular chunk of knowledge context extracted from a KnowledgeDocument."""
    chunk_id: str
    doc_id: str
    text: str
    chunk_index: int = 0
    embedding_id: Optional[str] = None
    relevance_score: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeContext(BaseModel):
    """Synthesized context returned from a KnowledgeRetriever query."""
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
