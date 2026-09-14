"""BEACON V2 — Phase 9 Knowledge RAG Persistence Store.

Provides durable SQLite persistence and query interfaces for ingested enterprise
knowledge documents, extracted metadata, versioned content hashes, and chunk index records.
"""

import json
import logging
import sqlite3
from typing import Any, Optional

from .models import (
    DocumentMetadata,
    DocumentStatus,
    DocumentType,
    KnowledgeChunk,
)

logger = logging.getLogger("beacon.knowledge.persistence")


class KnowledgePersistenceError(RuntimeError):
    """Raised when storing or querying knowledge artifacts in SQLite fails."""
    pass


class KnowledgePersistenceStore:
    """Manages SQLite storage for Phase 9 knowledge documents and retrieval chunks."""

    def __init__(self, db_path: str = "beacon.sqlite3"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes tables for knowledge documents and chunk indexes."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    document_id TEXT PRIMARY KEY,
                    application_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    storage_path TEXT NOT NULL DEFAULT '',
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    application_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    page_start INTEGER,
                    page_end INTEGER,
                    heading TEXT,
                    section TEXT,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (document_id) REFERENCES knowledge_documents(document_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_kdocs_app_status
                ON knowledge_documents(application_id, status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_kdocs_app_hash
                ON knowledge_documents(application_id, content_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_kchunks_app_doc
                ON knowledge_chunks(application_id, document_id)
            """)
            conn.commit()

    def save_document(self, meta: DocumentMetadata) -> None:
        """Persists or updates a knowledge document metadata record."""
        try:
            with self._get_conn() as conn:
                payload_json = json.dumps(meta.model_dump(), default=str)
                conn.execute("""
                    INSERT OR REPLACE INTO knowledge_documents (
                        document_id, application_id, filename, document_type,
                        content_hash, size_bytes, status, page_count, chunk_count,
                        storage_path, error_message, created_at, updated_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    meta.document_id,
                    meta.application_id,
                    meta.filename,
                    meta.document_type.value,
                    meta.content_hash,
                    meta.size_bytes,
                    meta.status.value,
                    meta.page_count,
                    meta.chunk_count,
                    meta.storage_path,
                    meta.error_message,
                    meta.created_at,
                    meta.updated_at,
                    payload_json,
                ))
                conn.commit()
                logger.info(f"Persisted knowledge document '{meta.document_id}' (status={meta.status}).")
        except Exception as exc:
            logger.error(f"Failed to persist document '{meta.document_id}': {exc}")
            raise KnowledgePersistenceError(f"Document persistence failure: {exc}") from exc

    def get_document(self, document_id: str) -> Optional[DocumentMetadata]:
        """Retrieves a document metadata record by ID."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT payload_json FROM knowledge_documents WHERE document_id = ?", (document_id,))
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return DocumentMetadata(**data)

    def get_document_by_hash(self, application_id: str, content_hash: str) -> Optional[DocumentMetadata]:
        """Retrieves an existing document in scope matching the given content hash."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT payload_json FROM knowledge_documents
                WHERE application_id = ? AND content_hash = ? AND status != 'ERROR'
                ORDER BY created_at DESC LIMIT 1
            """, (application_id, content_hash))
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return DocumentMetadata(**data)

    def list_documents(self, application_id: Optional[str] = None) -> list[DocumentMetadata]:
        """Lists document records filtered by authorized application scope."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if application_id:
                cursor.execute("""
                    SELECT payload_json FROM knowledge_documents
                    WHERE application_id = ? ORDER BY created_at DESC
                """, (application_id,))
            else:
                cursor.execute("""
                    SELECT payload_json FROM knowledge_documents
                    ORDER BY created_at DESC
                """)
            rows = cursor.fetchall()
            return [DocumentMetadata(**json.loads(r["payload_json"])) for r in rows]

    def update_document_status(
        self,
        document_id: str,
        status: DocumentStatus,
        page_count: Optional[int] = None,
        chunk_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[DocumentMetadata]:
        """Updates lifecycle state and metrics of an existing document."""
        doc = self.get_document(document_id)
        if not doc:
            return None

        doc.status = status
        if page_count is not None:
            doc.page_count = page_count
        if chunk_count is not None:
            doc.chunk_count = chunk_count
        if error_message is not None:
            doc.error_message = error_message
        self.save_document(doc)
        return doc

    def save_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        """Persists a batch of knowledge chunks into SQLite."""
        if not chunks:
            return
        try:
            with self._get_conn() as conn:
                for chunk in chunks:
                    payload_json = json.dumps(chunk.model_dump(), default=str)
                    conn.execute("""
                        INSERT OR REPLACE INTO knowledge_chunks (
                            chunk_id, document_id, application_id, chunk_index,
                            text, fingerprint, page_start, page_end, heading,
                            section, created_at, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.application_id,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.fingerprint,
                        chunk.metadata.page_start,
                        chunk.metadata.page_end,
                        chunk.metadata.heading,
                        chunk.metadata.section,
                        chunk.created_at,
                        payload_json,
                    ))
                conn.commit()
                logger.info(f"Persisted {len(chunks)} chunks for document '{chunks[0].document_id}'.")
        except Exception as exc:
            logger.error(f"Failed to persist knowledge chunks: {exc}")
            raise KnowledgePersistenceError(f"Chunk persistence failure: {exc}") from exc

    def list_chunks_for_document(self, document_id: str) -> list[KnowledgeChunk]:
        """Retrieves all indexed chunks belonging to a specific document."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT payload_json FROM knowledge_chunks
                WHERE document_id = ? ORDER BY chunk_index ASC
            """, (document_id,))
            rows = cursor.fetchall()
            return [KnowledgeChunk(**json.loads(r["payload_json"])) for r in rows]

    def list_chunks_for_application(self, application_id: str, ready_only: bool = True) -> list[KnowledgeChunk]:
        """Retrieves all indexed knowledge chunks for an application scope."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if ready_only:
                cursor.execute("""
                    SELECT c.payload_json FROM knowledge_chunks c
                    JOIN knowledge_documents d ON c.document_id = d.document_id
                    WHERE c.application_id = ? AND d.status = 'READY'
                    ORDER BY c.chunk_index ASC
                """, (application_id,))
            else:
                cursor.execute("""
                    SELECT payload_json FROM knowledge_chunks
                    WHERE application_id = ? ORDER BY chunk_index ASC
                """, (application_id,))
            rows = cursor.fetchall()
            return [KnowledgeChunk(**json.loads(r["payload_json"])) for r in rows]

    def delete_document(self, document_id: str) -> bool:
        """Deletes a document and all associated chunks from SQLite."""
        try:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
                cursor = conn.execute("DELETE FROM knowledge_documents WHERE document_id = ?", (document_id,))
                conn.commit()
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"Deleted knowledge document '{document_id}' and all its chunks.")
                return deleted
        except Exception as exc:
            logger.error(f"Failed to delete document '{document_id}': {exc}")
            raise KnowledgePersistenceError(f"Document deletion failure: {exc}") from exc


knowledge_persistence = KnowledgePersistenceStore()
