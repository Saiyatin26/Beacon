"""Stage 2e — Dedup and grounding via Atlas Vector Search.

Before treating a freshly-proposed candidate as new, embed it and search
already-mined invariants for near-duplicates. This does two things:
  1. Prevents re-mining the same rule under different wording.
  2. Gives the LLM nearby confirmed invariants as few-shot grounding context
     on the next call, which is the concrete mechanism for cutting down
     hallucinated rules (architecture doc Section 2, citing the ~40-50%
     hallucination figure from prior-art research).

Requires an Atlas Search vector index named 'invariant_vector_index' on the
'embedding' field of the invariants collection (create via Atlas UI/CLI —
pymongo cannot create vector indexes itself, see common/db.py).
"""

import logging
from typing import Any

try:
    import voyageai
except ImportError:
    voyageai = None

from common.config import settings
from common.db import invariants_col

logger = logging.getLogger(__name__)
_voyage_client = None
SIMILARITY_THRESHOLD = 0.92


from typing import Any

def _get_voyage() -> Any:
    global _voyage_client
    if _voyage_client is None:
        if voyageai is None:
            raise ImportError("voyageai is not installed")
        _voyage_client = voyageai.Client(api_key=settings.voyage_api_key)
    return _voyage_client


def embed_condition(condition_text: str) -> list[float]:
    try:
        voyage = _get_voyage()
        result = voyage.embed([condition_text], model="voyage-3", input_type="document")
        return result.embeddings[0]
    except Exception as exc:
        logger.debug(f"Voyage AI embedding unavailable: {exc}")
        return []


def find_similar(condition_text: str, top_k: int = 5) -> list[dict]:
    """Returns already-stored invariants whose condition is semantically close
    to condition_text, most-similar first. Empty list if nothing is close."""
    try:
        vector = embed_condition(condition_text)
        if not vector:
            return []
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "invariant_vector_index",
                    "path": "embedding",
                    "queryVector": vector,
                    "numCandidates": 50,
                    "limit": top_k,
                }
            },
            {"$project": {"invariant_id": 1, "condition": 1, "consequence": 1,
                           "score": {"$meta": "vectorSearchScore"}}},
        ]
        col = invariants_col()
        if col is None:
            return []
        results = list(col.aggregate(pipeline))
        return [r for r in results if r.get("score", 0.0) >= SIMILARITY_THRESHOLD]
    except Exception:
        return []


def store_invariant(validated_invariant_dict: dict, condition_text: str) -> None:
    try:
        emb = embed_condition(condition_text)
        if emb:
            validated_invariant_dict["embedding"] = emb
        col = invariants_col()
        if col is not None:
            col.update_one(
                {"invariant_id": validated_invariant_dict["invariant_id"]},
                {"$set": validated_invariant_dict},
                upsert=True,
            )
    except Exception as exc:
        logger.debug(f"Atlas invariant store skipped: {exc}")
