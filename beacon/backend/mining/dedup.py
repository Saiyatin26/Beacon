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

import voyageai
from common.config import settings
from common.db import invariants_col

_voyage_client = None
SIMILARITY_THRESHOLD = 0.92


def _get_voyage() -> voyageai.Client:
    global _voyage_client
    if _voyage_client is None:
        _voyage_client = voyageai.Client(api_key=settings.voyage_api_key)
    return _voyage_client


def embed_condition(condition_text: str) -> list[float]:
    result = _get_voyage().embed([condition_text], model="voyage-3", input_type="document")
    return result.embeddings[0]


def find_similar(condition_text: str, top_k: int = 5) -> list[dict]:
    """Returns already-stored invariants whose condition is semantically close
    to condition_text, most-similar first. Empty list if nothing is close."""
    vector = embed_condition(condition_text)
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
    results = list(invariants_col().aggregate(pipeline))
    return [r for r in results if r["score"] >= SIMILARITY_THRESHOLD]


def store_invariant(validated_invariant_dict: dict, condition_text: str) -> None:
    validated_invariant_dict["embedding"] = embed_condition(condition_text)
    invariants_col().update_one(
        {"invariant_id": validated_invariant_dict["invariant_id"]},
        {"$set": validated_invariant_dict},
        upsert=True,
    )
