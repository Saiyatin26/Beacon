"""BEACON V2 — Phase 5 Business Rule Registry & Persistence.

Provides CRUD operations, version history tracking, status management, and SQLite persistence
for domain-independent BusinessRule objects with explicit persistence failure propagation.
"""

from datetime import datetime, timezone
import json
import logging
import sqlite3
import threading
from typing import Any, Optional, Union

from .models import (
    BusinessRule,
    RuleConditionNode,
    RuleSeverity,
    RuleSource,
    RuleStatus,
)
from .normalizer import rule_normalizer
from .validator import rule_validator

from common.config import settings

logger = logging.getLogger("beacon.rules.registry")


class RulePersistenceError(RuntimeError):
    """Raised when writing or updating a rule in persistent storage fails."""
    pass


class RuleRegistry:
    """Thread-safe, SQLite-backed repository for BusinessRule lifecycle and versioning."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = str(db_path) if db_path and db_path != "beacon.sqlite3" else str(settings.database_path)
        self._lock = threading.Lock()
        self._memory_rules: dict[str, dict[int, BusinessRule]] = {}
        self._init_db()

    def _init_db(self) -> None:
        """Initializes business rule database schema in SQLite if not exists."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS beacon_business_rules (
                        rule_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        description TEXT,
                        source TEXT NOT NULL,
                        status TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        scope TEXT,
                        fingerprint TEXT NOT NULL,
                        rule_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (rule_id, version)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS beacon_controlled_evaluations (
                        evaluation_id TEXT PRIMARY KEY,
                        bundle_id TEXT,
                        application_id TEXT,
                        overall_verdict TEXT NOT NULL,
                        evaluation_fingerprint TEXT NOT NULL,
                        evaluation_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not initialize SQLite table for rules (using in-memory): {exc}")

    def register_rule(self, rule: BusinessRule) -> BusinessRule:
        """Validates, computes fingerprint, and registers a new BusinessRule or initial version.

        Raises:
            RulePersistenceError if database write fails.
        """
        is_valid, errors = rule_validator.validate_rule(rule)
        if not is_valid:
            rule.status = RuleStatus.INVALID
            logger.warning(f"Registering invalid rule '{rule.rule_id}': {errors}")

        if not rule.fingerprint:
            rule.fingerprint = rule_normalizer.compute_rule_fingerprint(rule)

        with self._lock:
            # Persist to SQLite first to guarantee durable storage
            self._persist_rule_to_db(rule)

            if rule.rule_id not in self._memory_rules:
                self._memory_rules[rule.rule_id] = {}
            self._memory_rules[rule.rule_id][rule.version] = rule

        return rule

    def update_rule(
        self,
        rule_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        condition: Optional[RuleConditionNode] = None,
        expected_behavior: Optional[Any] = None,
        severity: Optional[RuleSeverity] = None,
        status: Optional[RuleStatus] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> BusinessRule:
        """Updates a rule by incrementing its version number and preserving version history."""
        existing = self.get_rule(rule_id)
        if not existing:
            raise KeyError(f"Rule with ID '{rule_id}' not found.")

        new_version = existing.version + 1
        updated_dict = existing.model_dump()
        updated_dict["version"] = new_version
        updated_dict["updated_at"] = datetime.now(timezone.utc)

        if name is not None:
            updated_dict["name"] = name
        if description is not None:
            updated_dict["description"] = description
        if condition is not None:
            updated_dict["condition"] = condition
        if expected_behavior is not None:
            updated_dict["expected_behavior"] = expected_behavior
        if severity is not None:
            updated_dict["severity"] = severity
        if status is not None:
            updated_dict["status"] = status
        if metadata is not None:
            updated_dict["metadata"] = metadata

        updated_rule = BusinessRule(**updated_dict)
        updated_rule.fingerprint = updated_rule.compute_fingerprint()

        return self.register_rule(updated_rule)

    def get_rule(self, rule_id: str, version: Optional[int] = None) -> Optional[BusinessRule]:
        """Retrieves a rule by ID and optional version (defaults to latest version)."""
        with self._lock:
            # Check in-memory first
            if rule_id in self._memory_rules:
                versions = self._memory_rules[rule_id]
                if version is not None:
                    return versions.get(version)
                if versions:
                    latest_ver = max(versions.keys())
                    return versions[latest_ver]

            # Try fetching from SQLite
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.cursor()
                    if version is not None:
                        cursor.execute(
                            "SELECT rule_json FROM beacon_business_rules WHERE rule_id = ? AND version = ?",
                            (rule_id, version),
                        )
                    else:
                        cursor.execute(
                            "SELECT rule_json FROM beacon_business_rules WHERE rule_id = ? ORDER BY version DESC LIMIT 1",
                            (rule_id,),
                        )
                    row = cursor.fetchone()
                    if row:
                        rule_data = json.loads(row[0])
                        rule = BusinessRule(**rule_data)
                        if rule_id not in self._memory_rules:
                            self._memory_rules[rule_id] = {}
                        self._memory_rules[rule_id][rule.version] = rule
                        return rule
            except Exception as exc:
                logger.debug(f"SQLite lookup failed for rule '{rule_id}': {exc}")

        return None

    def list_rules(
        self,
        status: Optional[RuleStatus] = None,
        scope: Optional[str] = None,
        latest_only: bool = True,
    ) -> list[BusinessRule]:
        """Lists all registered business rules matching filters."""
        rules: list[BusinessRule] = []

        with self._lock:
            # Load all from SQLite into memory cache if empty
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT rule_json FROM beacon_business_rules")
                    for row in cursor.fetchall():
                        rule_data = json.loads(row[0])
                        r = BusinessRule(**rule_data)
                        if r.rule_id not in self._memory_rules:
                            self._memory_rules[r.rule_id] = {}
                        self._memory_rules[r.rule_id][r.version] = r
            except Exception:
                pass

            for rule_id, versions in self._memory_rules.items():
                if latest_only:
                    if versions:
                        latest_ver = max(versions.keys())
                        r = versions[latest_ver]
                        if status is None or r.status == status:
                            if scope is None or r.scope == scope:
                                rules.append(r)
                else:
                    for r in versions.values():
                        if status is None or r.status == status:
                            if scope is None or r.scope == scope:
                                rules.append(r)

        rules.sort(key=lambda r: (r.rule_id, r.version))
        return rules

    def disable_rule(self, rule_id: str) -> Optional[BusinessRule]:
        """Marks latest version of a rule as DISABLED."""
        r = self.get_rule(rule_id)
        if not r:
            return None
        r.status = RuleStatus.DISABLED
        self.register_rule(r)
        return r

    def delete_rule(self, rule_id: str) -> bool:
        """Deletes a rule and all its versions."""
        with self._lock:
            self._memory_rules.pop(rule_id, None)
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM beacon_business_rules WHERE rule_id = ?", (rule_id,))
                    conn.commit()
                return True
            except Exception as exc:
                logger.error(f"Error deleting rule '{rule_id}': {exc}")
                raise RulePersistenceError(f"Failed to delete rule '{rule_id}': {exc}") from exc

    def clear(self) -> None:
        """Clears all rules from memory and SQLite (useful for testing)."""
        with self._lock:
            self._memory_rules.clear()
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM beacon_business_rules")
                    cursor.execute("DELETE FROM beacon_controlled_evaluations")
                    conn.commit()
            except Exception:
                pass

    def _persist_rule_to_db(self, rule: BusinessRule) -> None:
        """Saves a single BusinessRule record to SQLite. Raises RulePersistenceError on DB failure."""
        try:
            rule_json = rule.model_dump_json()
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO beacon_business_rules (
                        rule_id, version, name, description, source, status, severity,
                        scope, fingerprint, rule_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rule.rule_id,
                        rule.version,
                        rule.name,
                        rule.description or "",
                        rule.source.value if hasattr(rule.source, "value") else str(rule.source),
                        rule.status.value if hasattr(rule.status, "value") else str(rule.status),
                        rule.severity.value if hasattr(rule.severity, "value") else str(rule.severity),
                        rule.scope or "global",
                        rule.fingerprint,
                        rule_json,
                        rule.created_at.isoformat(),
                        rule.updated_at.isoformat(),
                    ),
                )
                conn.commit()
        except Exception as exc:
            logger.error(f"SQLite persist failed for rule '{rule.rule_id}': {exc}")
            raise RulePersistenceError(f"Failed to persist rule '{rule.rule_id}' to database: {exc}") from exc


rule_registry = RuleRegistry()
