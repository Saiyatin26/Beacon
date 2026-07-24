"""Thin MongoDB Atlas client wrapper. Every stage that needs storage (invariant
dedup, certification runs, drift time-series) goes through this module rather
than opening its own connection.

Collections used (architecture doc Section 5):
  - invariants          candidate + validated invariants, with vector index for dedup
  - oracles              synthesized executable oracles (Stage 3)
  - certification_runs   one document per Stage 4 run (score + violations)
  - drift_samples        time-series documents from Stage 5
"""

from pymongo import MongoClient
from pymongo.collection import Collection
from .config import settings

_client = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        if not settings.mongodb_atlas_uri:
            raise RuntimeError(
                "MONGODB_ATLAS_URI is not set. Copy .env.example to .env and fill it in."
            )
        _client = MongoClient(settings.mongodb_atlas_uri)
    return _client


def get_db():
    return get_client()[settings.mongodb_db_name]


def invariants_col() -> Collection:
    return get_db()["invariants"]


def oracles_col() -> Collection:
    return get_db()["oracles"]


def certification_runs_col() -> Collection:
    return get_db()["certification_runs"]


def drift_samples_col() -> Collection:
    return get_db()["drift_samples"]


def ensure_indexes():
    """Call once at startup. The vector index itself (for invariants_col) must be
    created in the Atlas UI/CLI as an Atlas Search index — pymongo can't create
    vector search indexes directly, so this only sets up the ordinary indexes."""
    invariants_col().create_index("invariant_id", unique=True)
    oracles_col().create_index("invariant_id", unique=True)
    certification_runs_col().create_index("run_id", unique=True)
    drift_samples_col().create_index([("run_timestamp", 1)])
