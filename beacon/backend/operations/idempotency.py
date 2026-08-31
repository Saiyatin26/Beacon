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
import time
from typing import Any, Optional, Tuple


from common.config import settings
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
    """Thread-safe, SQLite-persisted idempotency manager enforcing project-safe isolation,
    material conflict rejection, and concurrent duplicate execution prevention.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._lock = threading.RLock()
        self._memory_cache: dict[str, dict[str, Any]] = {}
        self._completion_events: dict[str, threading.Event] = {}
        if db_path is None:
            self._db_path = str(settings.database_path)
        else:
            self._db_path = str(db_path)
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
        wait_timeout: float = 10.0,
    ) -> Tuple[Optional[dict[str, Any]], Optional[int]]:
        """Checks if an operation has already been executed or is currently running with this idempotency key.

        Returns:
            (response_data, status_code) if cached completed/failed result exists or in-progress status,
            (None, None) if this is a new operation reserved for execution by the caller.

        Raises:
            IdempotencyConflictError (HTTP 409) if the key was already used with a different payload.
        """
        if not idempotency_key:
            return None, None

        scoped_key = self._make_scoped_key(project_id, endpoint, idempotency_key)
        req_hash = compute_canonical_request_hash(request_payload)
        now = datetime.now(timezone.utc).isoformat()
        event_to_wait: Optional[threading.Event] = None

        with self._lock:
            # 1. Attempt atomic DB-level reservation using unique PRIMARY KEY insert (no INSERT OR REPLACE)
            is_owner = False
            db_error: Optional[str] = None
            try:
                with sqlite3.connect(self._db_path, timeout=10.0) as conn:
                    conn.execute("""
                        INSERT INTO operations_idempotency (
                            scoped_key, project_id, endpoint, idempotency_key,
                            request_hash, status, response_json, status_code, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'IN_PROGRESS', NULL, NULL, ?, ?)
                    """, (
                        scoped_key, project_id, endpoint, idempotency_key,
                        req_hash, now, now
                    ))
                    conn.commit()
                is_owner = True
            except sqlite3.IntegrityError:
                # Key already exists in database; this is a duplicate or subsequent request
                is_owner = False
            except Exception as exc:
                # UNKNOWN DATABASE STATE MUST NEVER BECOME IDEMPOTENCY OWNERSHIP
                is_owner = False
                db_error = str(exc)
                logger.error(f"Idempotency database reservation failure for key '{idempotency_key}': {exc}")
                log_operational_event(
                    event="idempotency_db_reservation_failed",
                    project_id=project_id,
                    level=logging.ERROR,
                    logger_name="beacon.idempotency",
                    outcome="DATABASE_ERROR",
                    error_category="DATABASE_FAILURE",
                    message="Idempotency reservation could not be confirmed due to database failure.",
                    extra={"idempotency_key": idempotency_key, "endpoint": endpoint},
                )

            if db_error is not None:
                # Database could not confirm ownership: fail safely and never execute
                return (
                    {
                        "error": "Idempotency reservation failed",
                        "detail": "The operation could not safely be started because idempotency ownership could not be confirmed by the database.",
                        "idempotency_key": idempotency_key,
                    },
                    500,
                )

            if is_owner:
                # First time seeing this key: caller becomes the single reservation owner
                self._memory_cache[scoped_key] = {
                    "scoped_key": scoped_key,
                    "project_id": project_id,
                    "endpoint": endpoint,
                    "idempotency_key": idempotency_key,
                    "request_hash": req_hash,
                    "status": "IN_PROGRESS",
                    "response_json": None,
                    "status_code": None,
                    "created_at": now,
                    "updated_at": now,
                }
                self._completion_events[scoped_key] = threading.Event()
                return None, None

            # 2. Key exists: load existing row from SQLite
            entry = None
            try:
                with sqlite3.connect(self._db_path, timeout=10.0) as conn:
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
                entry = self._memory_cache.get(scoped_key)

            if not entry:
                # Database state could not be loaded: fail safely, do NOT assume ownership
                logger.error(f"Could not load existing idempotency record for key '{idempotency_key}'")
                return (
                    {
                        "error": "Idempotency state retrieval failed",
                        "detail": "The existing operation state could not safely be retrieved.",
                        "idempotency_key": idempotency_key,
                    },
                    500,
                )


            # 3. Compare canonical request hash: different payload -> 409 Conflict
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

            # 4. Same request hash: inspect status
            status = entry.get("status")

            # 4a. COMPLETED: return cached successful response
            if status == "COMPLETED" and entry.get("response_json"):
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

            # 4b. FAILED: return stored failure explicitly (never treat as IN_PROGRESS!)
            if status == "FAILED":
                failed_data = {}
                if entry.get("response_json"):
                    try:
                        failed_data = json.loads(entry["response_json"])
                    except Exception:
                        failed_data = {"status": "FAILED", "detail": "Prior operation failed."}
                else:
                    failed_data = {"status": "FAILED", "detail": "Prior operation failed."}
                status_code = entry.get("status_code", 500)
                log_operational_event(
                    event="idempotent_failure_replayed",
                    project_id=project_id,
                    level=logging.WARNING,
                    logger_name="beacon.idempotency",
                    outcome="FAILED_REPLAYED",
                    message=f"Replayed existing failed status for idempotency key '{idempotency_key}'",
                )
                return failed_data, status_code

            # 4c. IN_PROGRESS: concurrent duplicate request!
            event_to_wait = self._completion_events.get(scoped_key)
            if not event_to_wait:
                event_to_wait = threading.Event()
                self._completion_events[scoped_key] = event_to_wait

        # Outside the lock: wait for the winning in-progress thread/process to complete
        if event_to_wait is not None:
            logger.info(
                f"Concurrent duplicate request for idempotency key '{idempotency_key}' "
                f"waiting up to {wait_timeout}s for in-progress operation to complete."
            )
            poll_interval = 0.05
            elapsed = 0.0
            while elapsed < wait_timeout:
                if event_to_wait.is_set():
                    break
                time.sleep(poll_interval)
                elapsed += poll_interval

                # Periodic DB check for cross-process completion
                with self._lock:
                    try:
                        with sqlite3.connect(self._db_path, timeout=5.0) as conn:
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
                                if entry.get("status") in ("COMPLETED", "FAILED"):
                                    break
                    except Exception:
                        pass

            # Final check of state after waiting
            with self._lock:
                entry = self._memory_cache.get(scoped_key)
                if not entry:
                    try:
                        with sqlite3.connect(self._db_path, timeout=5.0) as conn:
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
                    except Exception:
                        pass

                if entry:
                    if entry.get("status") == "COMPLETED" and entry.get("response_json"):
                        try:
                            cached_data = json.loads(entry["response_json"])
                            status_code = entry.get("status_code", 200)
                            return cached_data, status_code
                        except Exception:
                            pass
                    elif entry.get("status") == "FAILED":
                        failed_data = {}
                        if entry.get("response_json"):
                            try:
                                failed_data = json.loads(entry["response_json"])
                            except Exception:
                                failed_data = {"status": "FAILED", "detail": "Prior operation failed."}
                        else:
                            failed_data = {"status": "FAILED", "detail": "Prior operation failed."}
                        return failed_data, entry.get("status_code", 500)

                # If still IN_PROGRESS after wait, return 202 Accepted (NEVER return None to prevent duplicate execution)
                return (
                    {
                        "status": "IN_PROGRESS",
                        "detail": f"Operation with idempotency key '{idempotency_key}' is currently running.",
                        "idempotency_key": idempotency_key,
                    },
                    202,
                )

        return None, None

    def record_completed(
        self,
        project_id: str,
        endpoint: str,
        idempotency_key: Optional[str],
        request_payload: Any,
        response_data: Any,
        status_code: int = 200,
    ) -> None:
        """Atomically updates the record to COMPLETED."""
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
                with sqlite3.connect(self._db_path, timeout=10.0) as conn:
                    conn.execute("""
                        UPDATE operations_idempotency
                        SET status = 'COMPLETED', response_json = ?, status_code = ?, updated_at = ?
                        WHERE scoped_key = ?
                    """, (resp_json, status_code, now, scoped_key))
                    conn.commit()
            except Exception as exc:
                logger.warning(f"Could not persist completed idempotency record: {exc}")

            # Wake up any waiting concurrent requests
            event = self._completion_events.pop(scoped_key, None)
            if event:
                event.set()

    def record_failed(
        self,
        project_id: str,
        endpoint: str,
        idempotency_key: Optional[str],
        request_payload: Any,
        error_message: str = "Operation failed",
        status_code: int = 500,
    ) -> None:
        """Atomically updates the record to FAILED and wakes up waiting concurrent requests."""
        if not idempotency_key:
            return

        scoped_key = self._make_scoped_key(project_id, endpoint, idempotency_key)
        req_hash = compute_canonical_request_hash(request_payload)
        now = datetime.now(timezone.utc).isoformat()
        safe_msg = scrub_secrets(str(error_message))
        err_data = {
            "status": "FAILED",
            "detail": safe_msg,
            "idempotency_key": idempotency_key,
        }
        err_json = json.dumps(err_data)

        with self._lock:
            entry = {
                "scoped_key": scoped_key,
                "project_id": project_id,
                "endpoint": endpoint,
                "idempotency_key": idempotency_key,
                "request_hash": req_hash,
                "status": "FAILED",
                "response_json": err_json,
                "status_code": status_code,
                "created_at": now,
                "updated_at": now,
            }
            self._memory_cache[scoped_key] = entry

            try:
                with sqlite3.connect(self._db_path, timeout=10.0) as conn:
                    conn.execute("""
                        UPDATE operations_idempotency
                        SET status = 'FAILED', response_json = ?, status_code = ?, updated_at = ?
                        WHERE scoped_key = ?
                    """, (err_json, status_code, now, scoped_key))
                    conn.commit()
            except Exception as exc:
                logger.warning(f"Could not persist failed idempotency record: {exc}")

            # Wake up any waiting concurrent requests
            event = self._completion_events.pop(scoped_key, None)
            if event:
                event.set()

    def clear(self) -> None:
        """Clears all idempotency records (used for test isolation)."""
        with self._lock:
            self._memory_cache.clear()
            self._completion_events.clear()
            try:
                with sqlite3.connect(self._db_path, timeout=10.0) as conn:
                    conn.execute("DELETE FROM operations_idempotency")
                    conn.commit()
            except Exception as exc:
                logger.warning(f"Error clearing operations_idempotency: {exc}")


# Module-level singleton
idempotency_manager = IdempotencyManager()


