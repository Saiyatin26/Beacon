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
from typing import Any, Optional, Union

from common.config import settings

logger = logging.getLogger("beacon.persistence")


def consolidate_database_architecture(
    target_db_path: Optional[str] = None,
    legacy_database_paths: Optional[list[Union[str, Path]]] = None,
    archive_migrated: bool = False,
) -> dict[str, Any]:
    """Consolidates secondary SQLite database tables into the canonical database.
    Supports explicit legacy DB paths, safe archiving, and duplicate prevention.
    Enables WAL mode and returns a summary of merged records.
    """
    canonical_path = Path(target_db_path or settings.database_path).resolve()
    canonical_path.parent.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "tables_migrated": 0,
        "records_merged": 0,
        "sources_migrated": [],
        "archived_sources": [],
    }

    # 1. Enable WAL mode on canonical database
    try:
        with sqlite3.connect(str(canonical_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.commit()
    except Exception as exc:
        logger.warning(f"Could not enable WAL mode on canonical DB: {exc}")

    # 2. Determine secondary database files to consolidate
    candidate_secondary_paths: list[Path] = []
    if legacy_database_paths is not None:
        candidate_secondary_paths = [Path(p).resolve() for p in legacy_database_paths]
    else:
        root = Path(__file__).resolve().parents[2]
        candidate_secondary_paths = [
            (root / "backend" / "beacon.sqlite3").resolve(),
        ]

    for sec_path in candidate_secondary_paths:
        if not sec_path.exists():
            continue
        if sec_path == canonical_path:
            continue

        try:
            logger.info(f"Consolidating secondary SQLite database '{sec_path}' into '{canonical_path}'...")
            sec_conn = sqlite3.connect(str(sec_path))
            main_conn = sqlite3.connect(str(canonical_path))
            try:
                sec_cursor = sec_conn.cursor()
                main_cursor = main_conn.cursor()

                # Get all table names in secondary DB
                sec_cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                tables = sec_cursor.fetchall()

                for table_name, create_sql in tables:
                    # Create table in main DB if it doesn't exist
                    if create_sql:
                        safe_sql = create_sql.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
                        try:
                            main_cursor.execute(safe_sql)
                            main_conn.commit()
                        except sqlite3.OperationalError:
                            pass

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

                results["sources_migrated"].append(str(sec_path))
                logger.info(f"Database consolidation complete for '{sec_path}'.")
            finally:
                sec_conn.close()
                main_conn.close()

            # 3. Safe Archival (Rename to .migrated instead of permanent deletion)
            if archive_migrated:
                import gc
                del sec_cursor, main_cursor
                gc.collect()
                migrated_archive_path = sec_path.with_suffix(".sqlite3.migrated")
                try:
                    sec_path.rename(migrated_archive_path)
                    results["archived_sources"].append(str(migrated_archive_path))
                    logger.info(f"Archived migrated database to '{migrated_archive_path}'.")
                except Exception as arch_exc:
                    logger.warning(f"Could not rename migrated DB to archive path: {arch_exc}")

        except Exception as exc:
            logger.error(f"Error during secondary database migration from '{sec_path}': {exc}")

    return results
