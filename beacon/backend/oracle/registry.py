"""Phase 8 — Versioned Oracle Registry and Oracle Set Management.

Provides an immutable, version-aware registry for language-independent
executable oracles and frozen Oracle Sets.
"""

from datetime import datetime, timezone
import logging
from typing import Optional

from .models import OracleDefinition, OracleSet, OracleStatus
from .serializer import compute_oracle_set_hash

logger = logging.getLogger(__name__)


class OracleRegistry:
    """Manages versioned, immutable Oracle definitions and frozen Oracle Sets."""

    def __init__(self):
        # oracle_id -> {version: OracleDefinition}
        self._oracles: dict[str, dict[int, OracleDefinition]] = {}
        # oracle_set_id -> OracleSet
        self._oracle_sets: dict[str, OracleSet] = {}

    def register_oracle(self, oracle: OracleDefinition) -> OracleDefinition:
        """Registers an oracle. If an oracle with the same ID exists with differing content,
        increments the version and preserves historical versions immutably.
        """
        oid = oracle.oracle_id
        if oid not in self._oracles:
            self._oracles[oid] = {oracle.version: oracle}
            return oracle

        versions_map = self._oracles[oid]
        latest_version_num = max(versions_map.keys())
        latest_oracle = versions_map[latest_version_num]

        # If identical content hash, return existing definition
        if latest_oracle.content_hash == oracle.content_hash:
            return latest_oracle

        # Different content hash -> Create new immutable version
        new_version_num = latest_version_num + 1
        new_oracle = oracle.model_copy(
            update={
                "version": new_version_num,
                "status": OracleStatus.ACTIVE,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Mark previous version superseded via immutable copy
        versions_map[latest_version_num] = latest_oracle.model_copy(
            update={"status": OracleStatus.SUPERSEDED}
        )
        versions_map[new_version_num] = new_oracle
        return new_oracle

    def get_oracle(self, oracle_id: str, version: Optional[int] = None) -> Optional[OracleDefinition]:
        """Retrieves a specific version of an oracle, or the latest version if omitted."""
        if oracle_id not in self._oracles:
            return None

        versions_map = self._oracles[oracle_id]
        if version is not None:
            return versions_map.get(version)

        latest_version_num = max(versions_map.keys())
        return versions_map.get(latest_version_num)

    def list_oracles(
        self,
        status: Optional[OracleStatus] = None,
        domain: Optional[str] = None,
        include_historical: bool = False,
    ) -> list[OracleDefinition]:
        """Lists registered oracles with optional status and domain filtering."""
        result: list[OracleDefinition] = []

        for oid, versions_map in self._oracles.items():
            if include_historical:
                target_oracles = list(versions_map.values())
            else:
                latest_v = max(versions_map.keys())
                target_oracles = [versions_map[latest_v]]

            for o in target_oracles:
                if status and o.status != status:
                    continue
                if domain and o.domain != domain:
                    continue
                result.append(o)

        return sorted(result, key=lambda x: x.oracle_id)

    def deactivate_oracle(self, oracle_id: str, version: Optional[int] = None) -> bool:
        """Deactivates an oracle by creating an immutable snapshot without deleting historical records."""
        if oracle_id not in self._oracles:
            return False

        versions_map = self._oracles[oracle_id]
        target_v = version if version is not None else max(versions_map.keys())
        if target_v not in versions_map:
            return False

        target = versions_map[target_v]
        versions_map[target_v] = target.model_copy(update={"status": OracleStatus.INACTIVE})
        return True

    def create_oracle_set(
        self,
        name: str,
        oracle_ids: list[str],
        domain: str = "default",
    ) -> OracleSet:
        """Freezes a deterministic collection of oracles into an immutable OracleSet."""
        resolved_oracles: list[OracleDefinition] = []
        for oid in oracle_ids:
            oracle = self.get_oracle(oid)
            if oracle is None:
                raise ValueError(f"Cannot create OracleSet: oracle #{oid} not found in registry.")
            resolved_oracles.append(oracle)

        # Compute composite hash from constituent content hashes
        content_hashes = [o.content_hash for o in resolved_oracles]
        set_hash = compute_oracle_set_hash(content_hashes)
        set_id = f"SET-{set_hash[:8]}"

        oracle_set = OracleSet(
            oracle_set_id=set_id,
            name=name,
            version=1,
            domain=domain,
            oracle_ids=[o.oracle_id for o in resolved_oracles],
            oracles=resolved_oracles,
            oracle_set_hash=set_hash,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        self._oracle_sets[set_id] = oracle_set
        return oracle_set

    def get_oracle_set(self, oracle_set_id: str) -> Optional[OracleSet]:
        """Retrieves a frozen OracleSet by ID."""
        return self._oracle_sets.get(oracle_set_id)

    def list_oracle_sets(self, domain: Optional[str] = None) -> list[OracleSet]:
        """Lists all registered OracleSets."""
        sets = list(self._oracle_sets.values())
        if domain:
            sets = [s for s in sets if s.domain == domain]
        return sorted(sets, key=lambda x: x.oracle_set_id)

    def clear(self):
        """Clears all registry state (used for test isolation)."""
        self._oracles.clear()
        self._oracle_sets.clear()


# Default module-level singleton
registry = OracleRegistry()
