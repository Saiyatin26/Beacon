# BEACON SQLite Backup, Disaster Recovery & Storage Guide

## Overview

BEACON utilizes local SQLite storage with Write-Ahead Logging (WAL) for persistent state management, including:
- Operational job lifecycle transitions (`operations_jobs`)
- Project-scoped idempotency reservations (`operations_idempotency`)
- User dataset metadata and records (`user_datasets`)
- Certification history and cryptographic evidence dossiers

This document details recommended backup topologies, live snapshots, restoration procedures, and recovery behaviors.

---

## 1. Storage Topology & Location

- **Default Database Path**: `./beacon.sqlite3`
- **Configurable Path**: Set via `BEACON_DATABASE_PATH` environment variable (e.g. `/var/lib/beacon/beacon.sqlite3`).
- **Associated Files**:
  - `beacon.sqlite3` (Main database file)
  - `beacon.sqlite3-wal` (Write-Ahead Log)
  - `beacon.sqlite3-shm` (Shared memory index)

---

## 2. Live Backup Procedures

### Method A: SQLite Online Backup API / CLI (Recommended)
Because SQLite uses WAL mode, taking a live backup using the `.backup` CLI command or SQLite Online Backup API produces a transactionally consistent copy without shutting down the server:

```bash
# Perform live consistent backup snapshot
sqlite3 /var/lib/beacon/beacon.sqlite3 ".backup /var/backups/beacon/beacon_$(date +%Y%m%d_%H%M%S).sqlite3"
```

### Method B: Offline File Copy Backup
If performing a raw file-system level copy:
1. Stop the BEACON server process (`systemctl stop beacon` or Docker stop).
2. Copy `beacon.sqlite3`, `beacon.sqlite3-wal`, and `beacon.sqlite3-shm` together to backup storage.
3. Restart the BEACON server process.

---

## 3. Restoration Procedure

1. **Stop the Application**:
   Ensure no active processes are writing to the database.
   ```bash
   systemctl stop beacon
   ```

2. **Restore Snapshot**:
   Replace the active database file with the target backup snapshot:
   ```bash
   cp /var/backups/beacon/beacon_20260824_120000.sqlite3 /var/lib/beacon/beacon.sqlite3
   rm -f /var/lib/beacon/beacon.sqlite3-wal /var/lib/beacon/beacon.sqlite3-shm
   ```

3. **Start the Application**:
   ```bash
   systemctl start beacon
   ```

4. **Startup Recovery Execution**:
   On application startup, BEACON automatically runs `recover_interrupted_operations()`:
   - Any jobs that were marked `IN_PROGRESS` or `RUNNING` at the time the backup snapshot was taken will be safely transitioned to `FAILED` with an explicit diagnostic note: `"Operation interrupted by server restart during recovery"`.
   - Completed certifications and idempotency records remain fully intact and reusable.
