"""Phase 17 — Authentication Rate Limiter.

Protects login and credential-verification endpoints against brute-force
dictionary attacks using a process-local sliding-window timestamp algorithm.
Note: For multi-node distributed clusters behind load balancers, rate limiting
is also enforced at the API gateway / reverse proxy tier.
"""

from collections import deque
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class AuthRateLimiter:
    """Sliding-window rate limiter for sensitive authentication endpoints."""

    def __init__(self, default_max_attempts: int = 10, default_window_seconds: int = 60):
        self._max_attempts = default_max_attempts
        self._window_seconds = default_window_seconds
        # key -> deque of timestamps
        self._attempts: dict[str, deque[float]] = {}

    def is_allowed(
        self,
        key: str,
        max_attempts: Optional[int] = None,
        window_seconds: Optional[int] = None,
    ) -> tuple[bool, int]:
        """Checks whether the key is within rate limits.

        Returns:
            (allowed: bool, retry_after_seconds: int)
        """
        limit = max_attempts or self._max_attempts
        window = window_seconds or self._window_seconds
        now = time.time()

        if key not in self._attempts:
            return True, 0

        q = self._attempts[key]
        # Evict timestamps older than sliding window
        while q and q[0] <= now - window:
            q.popleft()

        if len(q) >= limit:
            oldest = q[0]
            retry_after = max(1, int(oldest + window - now))
            return False, retry_after

        return True, 0

    def record_attempt(self, key: str):
        """Records an authentication attempt for the key."""
        now = time.time()
        q = self._attempts.setdefault(key, deque())
        q.append(now)

    def reset(self, key: Optional[str] = None):
        """Clears recorded attempts for a specific key or all keys."""
        if key:
            self._attempts.pop(key, None)
        else:
            self._attempts.clear()

    def clear(self):
        """Alias for reset() for clean test teardowns."""
        self._attempts.clear()


# Default singleton instance
auth_rate_limiter = AuthRateLimiter()
