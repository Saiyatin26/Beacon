"""BEACON V2 — Phase 3 Immutable InputSet & Same-Input Guarantee Contract.

Provides immutable, content-hashed input set models ensuring that Reference and Target
applications receive logically identical canonical inputs during paired execution.
"""

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


from common.contracts import CanonicalInput, compute_canonical_input_hash


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """Computes a stable 64-character SHA-256 digest of canonical input payload values."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CanonicalInputItem(BaseModel):
    """An individual, sequence-indexed canonical input item with cryptographic hash."""
    model_config = ConfigDict(frozen=True)

    input_id: str = ""
    sequence: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    input_hash: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.input_hash and self.payload:
            object.__setattr__(self, "input_hash", compute_payload_hash(self.payload))
        if not self.input_id:
            h = self.input_hash or compute_payload_hash(self.payload)
            object.__setattr__(self, "input_id", f"inp_{self.sequence:04d}_{h[:8]}")

    def to_canonical_input(self) -> CanonicalInput:
        """Returns an independent CanonicalInput copy for execution."""
        import copy
        return CanonicalInput(
            input_id=self.input_id,
            payload=copy.deepcopy(self.payload),
            values=copy.deepcopy(self.payload),
            input_hash=self.input_hash,
            provenance=copy.deepcopy(self.provenance),
        )


def compute_input_set_hash(inputs: Union[list[CanonicalInputItem], tuple[CanonicalInputItem, ...]], source: str = "", version: str = "v2.0") -> str:
    """Computes a deterministic SHA-256 content hash across all inputs in sequence."""
    elements = [
        {
            "sequence": item.sequence,
            "input_id": item.input_id,
            "input_hash": compute_payload_hash(item.payload) if item.payload else item.input_hash,
        }
        for item in sorted(inputs, key=lambda x: x.sequence)
    ]
    manifest = {
        "version": version,
        "source": source,
        "input_count": len(inputs),
        "elements": elements,
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class InputSet(BaseModel):
    """Immutable, content-addressed collection of canonical inputs for paired execution.
    
    Guarantees that both Reference and Target adapters execute against the identical
    deterministic input domain and prevents silent post-creation mutation.
    """
    model_config = ConfigDict(frozen=True)

    input_set_id: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "explicit_inputs"
    input_count: int = 0
    inputs: tuple[CanonicalInputItem, ...] = Field(default_factory=tuple)
    canonicalization_version: str = "v2.0"
    content_hash: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.inputs and not isinstance(self.inputs, tuple):
            object.__setattr__(self, "inputs", tuple(self.inputs))

        if not self.inputs:
            object.__setattr__(self, "input_count", 0)
        else:
            object.__setattr__(self, "input_count", len(self.inputs))

        if not self.content_hash:
            computed_hash = compute_input_set_hash(
                self.inputs, source=self.source, version=self.canonicalization_version
            )
            object.__setattr__(self, "content_hash", computed_hash)

        if not self.input_set_id:
            h = self.content_hash[:12] if self.content_hash else "empty"
            object.__setattr__(self, "input_set_id", f"INPSET-{h}")


    def verify_content_hash(self) -> bool:
        """Verifies that the content hash matches the recomputed hash over all inputs."""
        expected = compute_input_set_hash(
            self.inputs, source=self.source, version=self.canonicalization_version
        )
        return self.content_hash == expected

    def get_input(self, input_id: str) -> Optional[CanonicalInputItem]:
        """Retrieves an input item by input_id."""
        for item in self.inputs:
            if item.input_id == input_id:
                return item
        return None

    def to_canonical_inputs(self) -> list[CanonicalInput]:
        """Returns deep copies of canonical inputs to prevent in-place adapter mutation."""
        return [item.to_canonical_input() for item in self.inputs]

    @classmethod
    def from_inputs(
        cls,
        inputs: list[Union[dict[str, Any], CanonicalInput, Any]],
        source: str = "explicit_inputs",
        provenance: Optional[dict[str, Any]] = None,
        input_set_id: Optional[str] = None,
    ) -> "InputSet":
        """Builds an immutable InputSet from arbitrary input dictionaries or models."""
        items: list[CanonicalInputItem] = []
        for seq, raw in enumerate(inputs):
            if isinstance(raw, CanonicalInputItem):
                items.append(raw)
            elif isinstance(raw, CanonicalInput):
                p = raw.get_data()
                h = raw.input_hash or compute_payload_hash(p)
                items.append(
                    CanonicalInputItem(
                        input_id=raw.input_id or f"inp_{seq:04d}_{h[:8]}",
                        sequence=seq,
                        payload=p,
                        input_hash=h,
                        provenance=raw.provenance,
                    )
                )
            elif hasattr(raw, "values") and isinstance(raw.values, dict):
                # CertificationTestInput or similar
                p = raw.values
                h = compute_payload_hash(p)
                i_id = getattr(raw, "input_id", None) or f"inp_{seq:04d}_{h[:8]}"
                prov = getattr(raw, "provenance", {}) or {}
                items.append(
                    CanonicalInputItem(
                        input_id=i_id,
                        sequence=seq,
                        payload=p,
                        input_hash=h,
                        provenance=prov if isinstance(prov, dict) else {},
                    )
                )
            elif isinstance(raw, dict):
                # Check if it has payload/values structure or raw dict
                p = raw.get("values") or raw.get("payload") or raw
                h = compute_payload_hash(p)
                i_id = raw.get("input_id") or f"inp_{seq:04d}_{h[:8]}"
                items.append(
                    CanonicalInputItem(
                        input_id=i_id,
                        sequence=seq,
                        payload=p,
                        input_hash=h,
                        provenance=raw.get("provenance", {}),
                    )
                )
            else:
                p = {"value": raw}
                h = compute_payload_hash(p)
                items.append(
                    CanonicalInputItem(
                        input_id=f"inp_{seq:04d}_{h[:8]}",
                        sequence=seq,
                        payload=p,
                        input_hash=h,
                        provenance={},
                    )
                )

        prov_dict = provenance or {}
        return cls(
            input_set_id=input_set_id or "",
            source=source,
            inputs=items,
            provenance=prov_dict,
        )
