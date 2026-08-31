"""Phase 20 Pre-Freeze Database Consolidation & Migration Utility.

Ensures that exactly one canonical SQLite database exists for the entire BEACON system.
If any legacy/secondary SQLite files exist (e.g. backend/beacon.sqlite3),
their tables and records are safely merged into the authoritative database path
without overwriting or losing existing user records, jobs, audits, notes, or datasets.
Also enables SQLite Write-Ahead Logging (WAL) for high concurrency and crash resilience.
"""

import logging
from pathlib import Path
import sqlite3
from typing import Optional

from common.config import settings

logger = logging.getLogger("beacon.persistence")


def consolidate_database_architecture(target_db_path: Optional[str] = None) -> dict[str, int]:
    """Consolidates secondary SQLite database tables into the canonical database.
    Enables WAL mode and returns a summary of merged records.
    """
    canonical_path = Path(target_db_path or settings.database_path).resolve()
    canonical_path.parent.mkdir(parents=True, exist_ok=True)

    results: dict[str, int] = {"tables_migrated": 0, "records_merged": 0}

    # 1. Enable WAL mode on canonical database
    try:
        with sqlite3.connect(str(canonical_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.commit()
    except Exception as exc:
        logger.warning(f"Could not enable WAL mode on canonical DB: {exc}")

    # 2. Check for known secondary database files
    root = Path(__file__).resolve().parents[2]
    candidate_secondary_paths = [
        root / "backend" / "beacon.sqlite3",
    ]

    for sec_path in candidate_secondary_paths:
        if not sec_path.exists():
            continue
        if sec_path.resolve() == canonical_path:
            continue

        try:
            logger.info(f"Consolidating secondary SQLite database '{sec_path}' into '{canonical_path}'...")
            with sqlite3.connect(str(sec_path)) as sec_conn, sqlite3.connect(str(canonical_path)) as main_conn:
                sec_cursor = sec_conn.cursor()
                main_cursor = main_conn.cursor()

                # Get all table names in secondary DB
                sec_cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                tables = sec_cursor.fetchall()

                for table_name, create_sql in tables:
                    # Create table in main DB if it doesn't exist
                    if create_sql:
                        main_cursor.execute(create_sql)
                        main_conn.commit()

                    # Fetch rows from secondary table
                    sec_cursor.execute(f"SELECT * FROM {table_name}")
                    rows = sec_cursor.fetchall()
                    if not rows:
                        continue

                    # Get column count
                    col_count = len(rows[0])
                    placeholders = ", ".join(["?"] * col_count)

                    # Insert or ignore to prevent primary key collision
                    main_cursor.executemany(
                        f"INSERT OR IGNORE INTO {table_name} VALUES ({placeholders})",
                        rows,
                    )
                    main_conn.commit()
                    results["tables_migrated"] += 1
                    results["records_merged"] += len(rows)

            logger.info(f"Database consolidation complete for '{sec_path}'.")
        except Exception as exc:
            logger.error(f"Error during secondary database migration from '{sec_path}': {exc}")

    return results
