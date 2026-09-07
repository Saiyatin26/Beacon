"""BEACON V2 — Phase 4 Centralized Evidence Status & Sufficiency Evaluator.

Provides a unified, deterministic contract to evaluate whether Phase 3 evidence
capture was complete and sufficient to support behavioral comparison.

Certification Invariant:
  CAPTURED -> sufficient for equivalence evaluation
  PARTIAL, NOT_AVAILABLE, NOT_SUPPORTED, FAILED, CONFIGURATION_ERROR, CAPTURE_ERROR -> insufficient (must yield INCONCLUSIVE, never EQUIVALENT)
"""

from typing import Any, Optional


class EvidenceSufficiency:
    """Centralized sufficiency evaluator for Phase 3 evidence status contracts."""

    SUFFICIENT_STATUSES = frozenset({"CAPTURED"})
    INSUFFICIENT_STATUSES = frozenset({
        "PARTIAL",
        "NOT_AVAILABLE",
        "NOT_SUPPORTED",
        "FAILED",
        "CONFIGURATION_ERROR",
        "CAPTURE_ERROR",
    })

    @classmethod
    def get_status_str(cls, obj: Any) -> Optional[str]:
        """Safely extracts status string from an evidence model, dictionary, or record."""
        if obj is None:
            return None
        if hasattr(obj, "status"):
            val = getattr(obj, "status")
            return str(getattr(val, "value", val)).upper()
        if hasattr(obj, "capture_status"):
            val = getattr(obj, "capture_status")
            return str(getattr(val, "value", val)).upper()
        if hasattr(obj, "log_status"):
            val = getattr(obj, "log_status")
            return str(getattr(val, "value", val)).upper()
        if isinstance(obj, dict):
            for k in ("status", "capture_status", "log_status"):
                if k in obj and obj[k] is not None:
                    val = obj[k]
                    return str(getattr(val, "value", val)).upper()
        return None

    @classmethod
    def is_sufficient(cls, obj: Any) -> bool:
        """Returns True if the evidence status is explicitly CAPTURED or unspecified (payload-based)."""
        st = cls.get_status_str(obj)
        if st is None:
            return True
        for insuff in cls.INSUFFICIENT_STATUSES:
            if insuff in st:
                return False
        return True

    @classmethod
    def is_insufficient(cls, obj: Any) -> bool:
        """Returns True if the evidence status is PARTIAL, NOT_SUPPORTED, NOT_AVAILABLE, FAILED, etc."""
        st = cls.get_status_str(obj)
        if st is None:
            return False
        for insuff in cls.INSUFFICIENT_STATUSES:
            if insuff in st:
                return True
        return False
