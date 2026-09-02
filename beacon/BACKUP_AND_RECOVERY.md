# BEACON Backup, Disaster Recovery & Persistence Guide

## Overview

BEACON employs a **Hybrid Persistence Architecture**:
- **SQLite (`beacon.sqlite3`)**: Core operational state, including job lifecycles (`operations_jobs`), idempotency keys (`operations_idempotency`), custom dataset registries (`user_datasets`), and local certification dossiers.
- **MongoDB Atlas (`MONGODB_ATLAS_URI`) (Optional)**: Invariant vector similarity search (Voyage AI embeddings), cross-service OracleSet registries, and high-throughput streaming drift time-series.

This guide details backup topologies, live snapshots, restoration procedures, and recovery behaviors for each persistence layer.

---

## 1. SQLite Storage & Backup (Core / Mandatory)

### Storage Topology
- **Default Database Path**: `./data/beacon.sqlite3`
- **Configurable Path**: Set via `BEACON_DATABASE_PATH` environment variable (e.g. `/var/lib/beacon/beacon.sqlite3` or `data/beacon.sqlite3`).
- **Files in WAL Mode**:
  - `beacon.sqlite3` (Main database file)
  - `beacon.sqlite3-wal` (Write-Ahead Log)
  - `beacon.sqlite3-shm` (Shared memory index)

### Method A: SQLite Online Backup API / CLI (Live Snapshot)
Because SQLite uses WAL mode, taking a live backup using the `.backup` CLI command or SQLite Online Backup API produces a transactionally consistent copy without shutting down the server:

```bash
# Perform live consistent backup snapshot
sqlite3 /var/lib/beacon/beacon.sqlite3 ".backup /var/backups/beacon/beacon_$(date +%Y%m%d_%H%M%S).sqlite3"
```

### Method B: Offline File Copy Backup
1. Stop the BEACON server process (`systemctl stop beacon` or Docker stop).
2. Copy `beacon.sqlite3`, `beacon.sqlite3-wal`, and `beacon.sqlite3-shm` together to backup storage.
3. Restart the BEACON server process.

### Restoration Procedure
1. Stop the application:
   ```bash
   systemctl stop beacon
   ```
2. Replace the active database file with the backup snapshot:
   ```bash
   cp /var/backups/beacon/beacon_20260824_120000.sqlite3 /var/lib/beacon/beacon.sqlite3
   rm -f /var/lib/beacon/beacon.sqlite3-wal /var/lib/beacon/beacon.sqlite3-shm
   ```
3. Start the application:
   ```bash
   systemctl start beacon
   ```

---

## 2. MongoDB Atlas Backup & Restoration (Optional Hybrid Domain Layer)

When `MONGODB_ATLAS_URI` is configured for enterprise invariant vector search and cloud drift storage:

### Backup Procedure
- **Atlas Continuous Cloud Backups**: Enable automated point-in-time recovery (PITR) snapshots in MongoDB Atlas cluster settings.
- **Manual CLI Backup (`mongodump`)**:
  ```bash
  mongodump --uri="$MONGODB_ATLAS_URI" --db=beacon --out=/var/backups/mongodb/beacon_$(date +%Y%m%d_%H%M%S)
  ```

### Restoration Procedure (`mongorestore`)
```bash
mongorestore --uri="$MONGODB_ATLAS_URI" --db=beacon --drop /var/backups/mongodb/beacon_20260824_120000/beacon
```

### Offline / Degradation Behavior
If MongoDB Atlas is unavailable or unconfigured, BEACON automatically degrades to standalone local operation:
- Candidate invariant deduplication seamlessly falls back to AST / lexical normalization.
- Operational job management and certification continue uninterrupted via SQLite.

---

## 3. In-Flight Jobs & Server Interruption Recovery

When BEACON starts up, the lifespan manager automatically executes `recover_interrupted_operations()`:
1. Identifies any active, non-terminal jobs (`PENDING`, `RUNNING`) remaining in `operations_jobs` from prior sudden power loss or process termination.
2. Safely transitions orphaned jobs to `FAILED` with explicit `error_details` (`"Server restarted while operation was in-flight"`).
3. Releases stale idempotency locks to permit clean client retries.
