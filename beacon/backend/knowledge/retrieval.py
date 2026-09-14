"""BEACON V2 — Phase 9 Scoped Knowledge Retrieval Engine.

Provides deterministic, scoped lexical relevance scoring (BM25 / TF-IDF)
over indexed knowledge chunks, enforcing strict application boundaries and
returning complete provenance metadata in a KnowledgeContext container.
"""

import collections
import logging
import math
import re
from typing import Optional, Sequence

from .models import (
    KnowledgeChunk,
    KnowledgeContext,
    KnowledgeQuery,
    RetrievalPolicy,
    RetrievalStatus,
    RetrievedChunk,
)
from .persistence import KnowledgePersistenceStore, knowledge_persistence

logger = logging.getLogger("beacon.knowledge.retrieval")


def tokenize(text: str) -> list[str]:
    """Tokenizes text into normalized lowercased alphanumeric words."""
    if not text:
        return []
    return re.findall(r"[a-zA-Z0-9_\-\$]+", text.lower())


class DeterministicLexicalRetriever:
    """Deterministic BM25 lexical retriever scoped to authorized application knowledge."""

    def __init__(self, persistence: Optional[KnowledgePersistenceStore] = None):
        self.persistence = persistence or knowledge_persistence
        # BM25 parameters
        self.k1 = 1.5
        self.b = 0.75

    def retrieve(
        self,
        query: str,
        application_id: str,
        top_k: int = 5,
        min_relevance_score: float = 0.01,
        policy: Optional[RetrievalPolicy] = None,
    ) -> KnowledgeContext:
        """Executes scoped lexical retrieval and returns a grounded KnowledgeContext package."""
        clean_query = query.strip() if query else ""
        bounded_top_k = max(1, min(top_k, 50))
        effective_min_score = min_relevance_score if policy is None else policy.min_relevance_score

        if not application_id or not application_id.strip():
            return KnowledgeContext(
                query=clean_query,
                application_id="unknown",
                status=RetrievalStatus.ERROR,
                retrieved_chunks=[],
                summary={"error": "application_id is required for scoped knowledge retrieval."},
            )

        # 1. Load active READY chunks for this application scope
        try:
            chunks = self.persistence.list_chunks_for_application(application_id, ready_only=True)
        except Exception as exc:
            logger.error(f"Error loading chunks for application '{application_id}': {exc}")
            return KnowledgeContext(
                query=clean_query,
                application_id=application_id,
                status=RetrievalStatus.ERROR,
                retrieved_chunks=[],
                summary={"error": f"Failed to access knowledge index: {exc}"},
            )

        if not chunks:
            return KnowledgeContext(
                query=clean_query,
                application_id=application_id,
                status=RetrievalStatus.SUCCESS_NO_RESULTS,
                retrieved_chunks=[],
                total_chunks_evaluated=0,
                summary={"message": f"No indexed knowledge documents found for application '{application_id}'."},
            )

        if not clean_query:
            return KnowledgeContext(
                query="",
                application_id=application_id,
                status=RetrievalStatus.SUCCESS_NO_RESULTS,
                retrieved_chunks=[],
                total_chunks_evaluated=len(chunks),
                summary={"message": "Query string was empty."},
            )

        # 2. Score chunks using deterministic BM25 lexical matching
        scored_chunks = self._score_chunks(clean_query, chunks)

        # 3. Filter by minimum relevance score
        matched = [
            (chunk, score)
            for chunk, score in scored_chunks
            if score >= effective_min_score
        ]

        # 4. Sort with deterministic tie-breaking (score DESC, chunk_id ASC)
        matched.sort(key=lambda item: (-item[1], item[0].chunk_id))

        # 5. Take top_k results
        top_results = matched[:bounded_top_k]

        # 6. Format RetrievedChunk records with full provenance
        retrieved_list: list[RetrievedChunk] = []
        source_filenames: set[str] = set()
        document_ids: set[str] = set()

        for chunk, score in top_results:
            source_filenames.add(chunk.metadata.filename)
            document_ids.add(chunk.document_id)
            retrieved_list.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    application_id=chunk.application_id,
                    filename=chunk.metadata.filename,
                    text=chunk.text,
                    relevance_score=round(score, 4),
                    chunk_index=chunk.chunk_index,
                    page_start=chunk.metadata.page_start,
                    page_end=chunk.metadata.page_end,
                    heading=chunk.metadata.heading,
                    section=chunk.metadata.section,
                    content_hash=chunk.metadata.content_hash,
                    metadata=chunk.metadata.custom_metadata,
                )
            )

        status = RetrievalStatus.SUCCESS_WITH_RESULTS if retrieved_list else RetrievalStatus.SUCCESS_NO_RESULTS
        effective_policy = policy or RetrievalPolicy(
            top_k=bounded_top_k,
            min_relevance_score=effective_min_score,
            retrieval_strategy="LEXICAL_BM25",
        )

        context = KnowledgeContext(
            query=clean_query,
            application_id=application_id,
            status=status,
            policy=effective_policy,
            retrieved_chunks=retrieved_list,
            total_chunks_evaluated=len(chunks),
            sources=sorted(list(source_filenames)),
            document_ids=sorted(list(document_ids)),
            summary={
                "matched_count": len(retrieved_list),
                "total_scope_chunks": len(chunks),
                "top_k": bounded_top_k,
                "min_score": effective_min_score,
            },
        )
        return context

    def _score_chunks(self, query: str, chunks: Sequence[KnowledgeChunk]) -> list[tuple[KnowledgeChunk, float]]:
        """Calculates BM25 relevance scores for all chunks in the scope."""
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        num_docs = len(chunks)
        chunk_token_lists = [tokenize(c.text) for c in chunks]
        doc_lengths = [len(tokens) for tokens in chunk_token_lists]
        avg_doc_len = sum(doc_lengths) / max(num_docs, 1)

        # 1. Calculate Document Frequency (DF) for each query token
        df: dict[str, int] = collections.defaultdict(int)
        for tokens in chunk_token_lists:
            unique_tokens = set(tokens)
            for q_tok in query_tokens:
                if q_tok in unique_tokens:
                    df[q_tok] += 1

        # 2. Calculate Inverse Document Frequency (IDF) with smoothing
        idf: dict[str, float] = {}
        for q_tok in set(query_tokens):
            n = df.get(q_tok, 0)
            # Standard BM25 smoothed IDF formula
            idf[q_tok] = math.log(1.0 + (num_docs - n + 0.5) / (n + 0.5))

        # 3. Score each chunk
        results: list[tuple[KnowledgeChunk, float]] = []
        lower_query = query.lower().strip()

        for idx, chunk in enumerate(chunks):
            tokens = chunk_token_lists[idx]
            doc_len = doc_lengths[idx]
            if doc_len == 0:
                continue

            tf_counts = collections.Counter(tokens)
            raw_score = 0.0

            for q_tok in query_tokens:
                freq = tf_counts.get(q_tok, 0)
                if freq > 0:
                    numerator = freq * (self.k1 + 1.0)
                    denominator = freq + self.k1 * (1.0 - self.b + self.b * (doc_len / max(avg_doc_len, 1.0)))
                    raw_score += idf.get(q_tok, 0.0) * (numerator / max(denominator, 1e-6))

            # Bonus for exact contiguous phrase match in chunk text
            if len(lower_query) > 3 and lower_query in chunk.text.lower():
                raw_score += 2.0

            # Bonus for heading / filename keyword match
            if chunk.metadata.heading and any(q_tok in chunk.metadata.heading.lower() for q_tok in query_tokens):
                raw_score += 1.0
            if any(q_tok in chunk.metadata.filename.lower() for q_tok in query_tokens):
                raw_score += 0.5

            if raw_score > 0.0:
                # Sigmoid normalization into [0.0, 1.0]
                normalized_score = 1.0 / (1.0 + math.exp(-raw_score / 3.0))
                results.append((chunk, float(normalized_score)))

        return results


knowledge_retriever = DeterministicLexicalRetriever()
