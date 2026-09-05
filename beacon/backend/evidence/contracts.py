"""BEACON V2 — Generic Evidence Contracts and Extension Boundary.

Defines extensible evidence categories, item models, and collector interfaces
capable of representing static code, runtime traces, input/output observations,
database state, exceptions, logs, and RAG/knowledge provenance.
"""

from abc import ABC, abstractmethod
from enum import Enum
import hashlib
import json
from typing import Any, Optional
from pydantic import BaseModel, Field


class EvidenceCategory(str, Enum):
    """Categorization of behavioral evidence items."""
    STATIC_CODE = "STATIC_CODE"
    RUNTIME_TRACE = "RUNTIME_TRACE"
    INPUT_OUTPUT = "INPUT_OUTPUT"
    EXCEPTION = "EXCEPTION"
    DATABASE_STATE = "DATABASE_STATE"
    FILE_STATE = "FILE_STATE"
    API_CALL = "API_CALL"
    EVENT = "EVENT"
    LOG = "LOG"
    KNOWLEDGE_RAG = "KNOWLEDGE_RAG"
    PROVENANCE = "PROVENANCE"


def compute_evidence_item_hash(payload: dict[str, Any]) -> str:
    """Computes deterministic SHA-256 hash for an evidence payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GenericEvidenceItem(BaseModel):
    """Generic structured unit of evidence with provenance and cryptographic hash."""
    evidence_id: str
    category: EvidenceCategory = EvidenceCategory.INPUT_OUTPUT
    source_type: str = "observation"
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_hash: str = ""
    timestamp: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.evidence_hash and self.payload:
            object.__setattr__(self, "evidence_hash", compute_evidence_item_hash(self.payload))


class EvidenceCollector(ABC):
    """Abstract collector for gathering and packaging behavioral evidence."""

    @abstractmethod
    def start_collection(self) -> None:
        """Initializes evidence collection for a certification run."""
        pass

    @abstractmethod
    def collect_event(self, category: EvidenceCategory, payload: dict[str, Any]) -> GenericEvidenceItem:
        """Records a new evidence event."""
        pass

    @abstractmethod
    def finalize_package(self) -> dict[str, Any]:
        """Finalizes and returns the complete evidence package."""
        pass
