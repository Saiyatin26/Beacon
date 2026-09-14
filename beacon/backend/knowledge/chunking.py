"""BEACON V2 — Phase 9 Deterministic Document Chunking Engine.

Splits extracted document text into bounded, overlapping chunks with deterministic
identities, content fingerprints, and precise page/heading provenance tracking.
"""

import hashlib
import logging
from typing import Optional

from .models import (
    ChunkMetadata,
    DocumentMetadata,
    ExtractedDocument,
    KnowledgeChunk,
)

logger = logging.getLogger("beacon.knowledge.chunking")

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 100


class ChunkingConfigurationError(ValueError):
    """Raised when chunk size or overlap parameters are invalid."""
    pass


class DeterministicChunker:
    """Performs deterministic, bounded text chunking across document pages and sections."""

    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP):
        if chunk_size <= 0:
            raise ChunkingConfigurationError(f"chunk_size must be positive, got {chunk_size}")
        if chunk_overlap < 0:
            raise ChunkingConfigurationError(f"chunk_overlap cannot be negative, got {chunk_overlap}")
        if chunk_overlap >= chunk_size:
            raise ChunkingConfigurationError(
                f"chunk_overlap ({chunk_overlap}) must be strictly less than chunk_size ({chunk_size})"
            )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(
        self,
        extracted: ExtractedDocument,
        doc_meta: DocumentMetadata,
    ) -> list[KnowledgeChunk]:
        """Produces an ordered sequence of deterministic knowledge chunks from an extracted document."""
        chunks: list[KnowledgeChunk] = []
        chunk_idx = 0

        # Strategy A: Page-aware chunking if individual pages with text are available
        if extracted.pages and any(len(p.text) > 0 for p in extracted.pages):
            for page in extracted.pages:
                if not page.text.strip():
                    continue

                page_chunks = self._chunk_text(
                    text=page.text,
                    page_num=page.page_number,
                    doc_meta=doc_meta,
                    start_index=chunk_idx,
                )
                chunks.extend(page_chunks)
                chunk_idx += len(page_chunks)

        # Strategy B: Fallback to normalized document text if no page granularity
        if not chunks and extracted.normalized_text.strip():
            fallback_chunks = self._chunk_text(
                text=extracted.normalized_text,
                page_num=1,
                doc_meta=doc_meta,
                start_index=0,
            )
            chunks.extend(fallback_chunks)

        logger.info(
            f"Chunked document '{doc_meta.document_id}' into {len(chunks)} chunks "
            f"(chunk_size={self.chunk_size}, overlap={self.chunk_overlap})."
        )
        return chunks

    def _chunk_text(
        self,
        text: str,
        page_num: Optional[int],
        doc_meta: DocumentMetadata,
        start_index: int,
    ) -> list[KnowledgeChunk]:
        """Splits a block of text into overlapping windows while respecting paragraph boundaries where practical."""
        results: list[KnowledgeChunk] = []
        text_len = len(text)
        if text_len == 0:
            return []

        step = self.chunk_size - self.chunk_overlap
        pos = 0
        local_idx = 0

        while pos < text_len:
            end_pos = min(pos + self.chunk_size, text_len)
            
            # If not at the very end of text, attempt to find a natural sentence/paragraph break within the window
            if end_pos < text_len:
                # Look for paragraph break (\n\n) or sentence boundary (. ) in last 25% of window
                window = text[pos:end_pos]
                break_point = -1
                p_break = window.rfind("\n\n")
                if p_break > int(self.chunk_size * 0.75):
                    break_point = p_break + 2
                else:
                    s_break = window.rfind(". ")
                    if s_break > int(self.chunk_size * 0.75):
                        break_point = s_break + 2
                
                if break_point > 0:
                    end_pos = pos + break_point

            chunk_text = text[pos:end_pos].strip()
            if chunk_text:
                current_chunk_index = start_index + local_idx
                # Compute stable chunk ID from document ID, index, and content hash
                content_digest = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:8]
                chunk_id = f"chk_{doc_meta.document_id}_{current_chunk_index:04d}_{content_digest}"

                metadata = ChunkMetadata(
                    document_id=doc_meta.document_id,
                    application_id=doc_meta.application_id,
                    filename=doc_meta.filename,
                    document_type=doc_meta.document_type,
                    content_hash=doc_meta.content_hash,
                    chunk_index=current_chunk_index,
                    page_start=page_num,
                    page_end=page_num,
                    character_start=pos,
                    character_end=end_pos,
                )

                chunk = KnowledgeChunk(
                    chunk_id=chunk_id,
                    document_id=doc_meta.document_id,
                    application_id=doc_meta.application_id,
                    chunk_index=current_chunk_index,
                    text=chunk_text,
                    metadata=metadata,
                )
                results.append(chunk)
                local_idx += 1

            pos += step
            if pos >= text_len or end_pos == text_len:
                break

        return results
