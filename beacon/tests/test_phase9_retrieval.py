"""BEACON V2 — Phase 9 Scoped Retrieval Test Suite.

Verifies deterministic lexical scoring, strict scope isolation, top-k bounding,
relevance thresholding, no-results handling, and retrieval fingerprint determinism.
"""

from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowledge.models import (
    ChunkMetadata,
    DocumentType,
    KnowledgeChunk,
    RetrievalPolicy,
    RetrievalStatus,
)
from knowledge.persistence import KnowledgePersistenceStore
from knowledge.retrieval import DeterministicLexicalRetriever


class TestPhase9KnowledgeRetrieval:
    """Detailed unit tests for retrieval scoring, scoping, thresholding, and determinism."""

    def test_lexical_scoring_and_keyword_relevance(self, tmp_path):
        """Retriever accurately ranks chunks with relevant keywords higher than unrelated chunks."""
        db_path = str(tmp_path / "test_retrieval.sqlite3")
        store = KnowledgePersistenceStore(db_path=db_path)
        retriever = DeterministicLexicalRetriever(persistence=store)

        meta = ChunkMetadata(
            document_id="doc_lex_1",
            application_id="app_lex_test",
            filename="policy.pdf",
            document_type=DocumentType.PDF,
            content_hash="hash123",
            chunk_index=0,
        )

        chunk_relevant = KnowledgeChunk(
            chunk_id="chk_rel_01",
            document_id="doc_lex_1",
            application_id="app_lex_test",
            chunk_index=0,
            text="Special discount pricing rules for premium tier retail customers.",
            metadata=meta,
        )
        chunk_unrelated = KnowledgeChunk(
            chunk_id="chk_unrel_02",
            document_id="doc_lex_1",
            application_id="app_lex_test",
            chunk_index=1,
            text="General warehouse maintenance schedule and employee break room guidelines.",
            metadata=meta,
        )

        # Create document record as READY
        from knowledge.models import DocumentMetadata, DocumentStatus
        store.save_document(
            DocumentMetadata(
                document_id="doc_lex_1",
                application_id="app_lex_test",
                filename="policy.pdf",
                document_type=DocumentType.PDF,
                content_hash="hash123",
                size_bytes=500,
                status=DocumentStatus.READY,
            )
        )
        store.save_chunks([chunk_relevant, chunk_unrelated])

        # Query relevant term
        ctx = retriever.retrieve(
            query="retail discount pricing",
            application_id="app_lex_test",
            top_k=5,
            min_relevance_score=0.01,
        )

        assert ctx.status == RetrievalStatus.SUCCESS_WITH_RESULTS
        assert len(ctx.retrieved_chunks) >= 1
        assert ctx.retrieved_chunks[0].chunk_id == "chk_rel_01"
        assert ctx.retrieved_chunks[0].relevance_score > 0.0

    def test_top_k_bounding_and_tie_breaking(self, tmp_path):
        """Retriever enforces bounded top_k and deterministic tie-breaking by chunk_id ASC."""
        db_path = str(tmp_path / "test_topk.sqlite3")
        store = KnowledgePersistenceStore(db_path=db_path)
        retriever = DeterministicLexicalRetriever(persistence=store)

        from knowledge.models import DocumentMetadata, DocumentStatus
        store.save_document(
            DocumentMetadata(
                document_id="doc_topk",
                application_id="app_topk",
                filename="doc.pdf",
                document_type=DocumentType.PDF,
                content_hash="hash_topk",
                size_bytes=500,
                status=DocumentStatus.READY,
            )
        )

        meta = ChunkMetadata(
            document_id="doc_topk",
            application_id="app_topk",
            filename="doc.pdf",
            document_type=DocumentType.PDF,
            content_hash="hash_topk",
            chunk_index=0,
        )

        # 5 chunks with identical text
        chunks = [
            KnowledgeChunk(
                chunk_id=f"chk_tie_{idx:02d}",
                document_id="doc_topk",
                application_id="app_topk",
                chunk_index=idx,
                text="Identical matching query keywords in every chunk.",
                metadata=meta,
            )
            for idx in [4, 1, 3, 0, 2]
        ]
        store.save_chunks(chunks)

        # Request top_k = 2
        ctx = retriever.retrieve(
            query="matching query keywords",
            application_id="app_topk",
            top_k=2,
            min_relevance_score=0.01,
        )

        assert len(ctx.retrieved_chunks) == 2
        # Deterministic tie-breaking by chunk_id ASC: chk_tie_00, chk_tie_01
        assert ctx.retrieved_chunks[0].chunk_id == "chk_tie_00"
        assert ctx.retrieved_chunks[1].chunk_id == "chk_tie_01"

    def test_retrieval_relevance_threshold_filtering(self, tmp_path):
        """Chunks scoring below min_relevance_score are filtered out."""
        db_path = str(tmp_path / "test_thresh.sqlite3")
        store = KnowledgePersistenceStore(db_path=db_path)
        retriever = DeterministicLexicalRetriever(persistence=store)

        from knowledge.models import DocumentMetadata, DocumentStatus
        store.save_document(
            DocumentMetadata(
                document_id="doc_th",
                application_id="app_th",
                filename="doc.pdf",
                document_type=DocumentType.PDF,
                content_hash="hash_th",
                size_bytes=500,
                status=DocumentStatus.READY,
            )
        )

        meta = ChunkMetadata(
            document_id="doc_th",
            application_id="app_th",
            filename="doc.pdf",
            document_type=DocumentType.PDF,
            content_hash="hash_th",
            chunk_index=0,
        )

        chunk = KnowledgeChunk(
            chunk_id="chk_low_01",
            document_id="doc_th",
            application_id="app_th",
            chunk_index=0,
            text="Unrelated text about lunar geography.",
            metadata=meta,
        )
        store.save_chunks([chunk])

        # Query unrelated term with threshold = 0.5 -> should return 0 results
        ctx = retriever.retrieve(
            query="credit card discount",
            application_id="app_th",
            min_relevance_score=0.5,
        )
        assert ctx.status == RetrievalStatus.SUCCESS_NO_RESULTS
        assert len(ctx.retrieved_chunks) == 0

    def test_empty_scope_and_empty_query_handling(self, tmp_path):
        """Retriever handles empty scopes, missing application IDs, and empty queries safely."""
        db_path = str(tmp_path / "test_empty.sqlite3")
        store = KnowledgePersistenceStore(db_path=db_path)
        retriever = DeterministicLexicalRetriever(persistence=store)

        # 1. Missing application_id -> ERROR
        ctx_no_app = retriever.retrieve(query="test", application_id="")
        assert ctx_no_app.status == RetrievalStatus.ERROR

        # 2. Scope with zero documents -> SUCCESS_NO_RESULTS
        ctx_empty_scope = retriever.retrieve(query="test", application_id="non_existent_app")
        assert ctx_empty_scope.status == RetrievalStatus.SUCCESS_NO_RESULTS
        assert len(ctx_empty_scope.retrieved_chunks) == 0
