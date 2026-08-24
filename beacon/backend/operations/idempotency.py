"""Phase 19 — Project-Safe Idempotency & Conflict Detection Subsystem for BEACON.

Enforces deterministic operation reuse, cross-project isolation, and 409 Conflict rejection
when an idempotency key is reused with a different request payload.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Optional, Tuple

from .errors import IdempotencyConflictError
from .logging_config import log_operational_event, scrub_secrets

logger = logging.getLogger("beacon.idempotency")


def compute_canonical_request_hash(payload: Any) -> str:
    """Computes a deterministic SHA-256 canonical hash of a request payload.
    Sorts dictionary keys and formats uniformly.
    """
    if payload is None:
        return hashlib.sha256(b"null").hexdigest()
    
    if hasattr(payload, "model_dump"):
        raw_data = payload.model_dump(mode="json")
    elif isinstance(payload, dict):
        raw_data = payload
    elif isinstance(payload, (list, tuple)):
        raw_data = list(payload)
    else:
        raw_data = str(payload)

    # Exclude client-transient fields if present in dictionary
    if isinstance(raw_data, dict):
        sanitized = {
            k: v for k, v in raw_data.items()
            if k not in ("request_id", "timestamp", "force_recompute", "client_timestamp")
        }
    else:
        sanitized = raw_data

    serialized = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class IdempotencyManager:
    """Thread-safe, SQLite-persisted idempotency manager enforcing project-safe isolation
    and material conflict rejection.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._lock = threading.RLock()
        self._memory_cache: dict[str, dict[str, Any]] = {}
        if db_path is None:
            backend_dir = Path(__file__).resolve().parent.parent
            self._db_path = str(backend_dir / "beacon.sqlite3")
        else:
            self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS operations_idempotency (
                        scoped_key TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        endpoint TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        request_hash TEXT NOT NULL,
                        status TEXT NOT NULL,
                        response_json TEXT,
                        status_code INTEGER,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_idem_project ON operations_idempotency(project_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_idem_created ON operations_idempotency(created_at)")
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not initialize operations_idempotency table: {exc}")

    def _make_scoped_key(self, project_id: str, endpoint: str, idempotency_key: str) -> str:
        """Constructs a tenant-isolated scoped key combining server-authoritative project_id,
        endpoint, and client idempotency key.
        """
        clean_proj = (project_id or "global").strip()
        clean_ep = endpoint.strip()
        clean_key = idempotency_key.strip()
        return f"{clean_proj}:{clean_ep}:{clean_key}"

    def check_or_reserve(
        self,
        project_id: str,
        endpoint: str,
        idempotency_key: Optional[str],
        request_payload: Any,
    ) -> Tuple[Optional[dict[str, Any]], Optional[int]]:
        """Checks if an operation has already been executed with this idempotency key.
        
        Returns:
            (response_data, status_code) if cached completed result exists,
            (None, None) if this is a new operation.
            
        Raises:
            IdempotencyConflictError (HTTP 409) if the key was already used with a different payload.
        """
        if not idempotency_key:
            return None, None

        scoped_key = self._make_scoped_key(project_id, endpoint, idempotency_key)
        req_hash = compute_canonical_request_hash(request_payload)

        with self._lock:
            # 1. Check in-memory cache
            entry = self._memory_cache.get(scoped_key)

            # 2. Check SQLite database if not in memory
            if not entry:
                try:
                    with sqlite3.connect(self._db_path) as conn:
                        conn.row_factory = sqlite3.Row
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT * FROM operations_idempotency WHERE scoped_key = ?",
                            (scoped_key,),
                        )
                        row = cursor.fetchone()
                        if row:
                            entry = dict(row)
                            self._memory_cache[scoped_key] = entry
                except Exception as exc:
                    logger.warning(f"Error querying operations_idempotency: {exc}")

            if not entry:
                # First time seeing this key: reserve in-progress
                self._reserve_in_progress(scoped_key, project_id, endpoint, idempotency_key, req_hash)
                return None, None

            # 3. Key exists: compare canonical request hash
            stored_hash = entry["request_hash"]
            if stored_hash != req_hash:
                err_msg = (
                    f"Idempotency conflict: Key '{idempotency_key}' in project '{project_id}' "
                    f"has already been used with a different request payload."
                )
                logger.warning(err_msg)
                log_operational_event(
                    event="idempotency_conflict_detected",
                    project_id=project_id,
                    level=logging.WARNING,
                    logger_name="beacon.idempotency",
                    outcome="CONFLICT",
                    error_category="IDEMPOTENCY_CONFLICT",
                    message=err_msg,
                    extra={
                        "idempotency_key": idempotency_key,
                        "endpoint": endpoint,
                        "project_id": project_id,
                    },
                )
                raise IdempotencyConflictError(
                    message=err_msg,
                    details={
                        "idempotency_key": idempotency_key,
                        "project_id": project_id,
                        "endpoint": endpoint,
                    },
                )

            # 4. Same request hash: if COMPLETED, return cached response
            if entry.get("status") == "COMPLETED" and entry.get("response_json"):
                try:
                    cached_data = json.loads(entry["response_json"])
                    status_code = entry.get("status_code", 200)
                    log_operational_event(
                        event="idempotent_result_reused",
                        project_id=project_id,
                        level=logging.INFO,
                        logger_name="beacon.idempotency",
                        outcome="REUSED",
                        message=f"Reused existing completed result for idempotency key '{idempotency_key}'",
                    )
                    return cached_data, status_code
                except Exception as exc:
                    logger.warning(f"Failed to decode cached idempotency response: {exc}")

            return None, None

    def _reserve_in_progress(
        self,
        scoped_key: str,
        project_id: str,
        endpoint: str,
        idempotency_key: str,
        request_hash: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        entry = {
            "scoped_key": scoped_key,
            "project_id": project_id,
            "endpoint": endpoint,
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
            "status": "IN_PROGRESS",
            "response_json": None,
            "status_code": None,
            "created_at": now,
            "updated_at": now,
        }
        self._memory_cache[scoped_key] = entry
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO operations_idempotency (
                        scoped_key, project_id, endpoint, idempotency_key,
                        request_hash, status, response_json, status_code, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    scoped_key, project_id, endpoint, idempotency_key,
                    request_hash, "IN_PROGRESS", None, None, now, now
                ))
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not reserve idempotency record: {exc}")

    def record_completed(
        self,
        project_id: str,
        endpoint: str,
        idempotency_key: Optional[str],
        request_payload: Any,
        response_data: Any,
        status_code: int = 200,
    ) -> None:
        """Atomically saves the completed response for an idempotency key."""
        if not idempotency_key:
            return

        scoped_key = self._make_scoped_key(project_id, endpoint, idempotency_key)
        req_hash = compute_canonical_request_hash(request_payload)
        now = datetime.now(timezone.utc).isoformat()

        if hasattr(response_data, "model_dump"):
            resp_dict = response_data.model_dump(mode="json")
        elif isinstance(response_data, dict):
            resp_dict = response_data
        else:
            resp_dict = {"data": str(response_data)}

        resp_json = json.dumps(resp_dict, default=str)

        with self._lock:
            entry = {
                "scoped_key": scoped_key,
                "project_id": project_id,
                "endpoint": endpoint,
                "idempotency_key": idempotency_key,
                "request_hash": req_hash,
                "status": "COMPLETED",
                "response_json": resp_json,
                "status_code": status_code,
                "created_at": now,
                "updated_at": now,
            }
            self._memory_cache[scoped_key] = entry

            try:
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO operations_idempotency (
                            scoped_key, project_id, endpoint, idempotency_key,
                            request_hash, status, response_json, status_code, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        scoped_key, project_id, endpoint, idempotency_key,
                        req_hash, "COMPLETED", resp_json, status_code, now, now
                    ))
                    conn.commit()
            except Exception as exc:
                logger.warning(f"Could not persist completed idempotency record: {exc}")

    def clear(self) -> None:
        """Clears all idempotency records (used for test isolation)."""
        with self._lock:
            self._memory_cache.clear()
            try:
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute("DELETE FROM operations_idempotency")
                    conn.commit()
            except Exception as exc:
                logger.warning(f"Error clearing operations_idempotency: {exc}")


# Module-level singleton
idempotency_manager = IdempotencyManager()
