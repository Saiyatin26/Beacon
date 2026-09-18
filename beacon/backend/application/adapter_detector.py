"""BEACON V2 — Automatic Adapter Resolution Engine.

Analyzes discovered repository entrypoints and deterministically resolves
ImplementationAdapters with strict fail-closed semantics (ADAPTER_AMBIGUOUS, ADAPTER_UNRESOLVED).
Preserves detection evidence and execution provenance.
"""

from enum import Enum
import importlib.util
import logging
from pathlib import Path
import sys
from typing import Any, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from common.contracts import AdapterRole, ImplementationAdapter
from certification.adapters import FunctionAdapter, PreserveCaseNormalizer
from .repository_service import DiscoveredEntrypoint, RepositoryAnalysisReport

logger = logging.getLogger("beacon.application.adapter_detector")


class AdapterResolutionStatus(str, Enum):
    """Authoritative status of automatic adapter resolution."""
    RESOLVED = "RESOLVED"
    ADAPTER_AMBIGUOUS = "ADAPTER_AMBIGUOUS"
    ADAPTER_UNRESOLVED = "ADAPTER_UNRESOLVED"


class AdapterResolutionResult(BaseModel):
    """Result of automatic adapter detection and resolution with verifiable evidence."""
    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    status: AdapterResolutionStatus
    method: str = "AUTOMATIC"
    role: str = "target"
    adapter_name: Optional[str] = None
    resolved_entrypoint: Optional[str] = None
    adapter_instance: Optional[Any] = None
    detection_evidence: dict[str, Any] = Field(default_factory=dict)
    candidates_count: int = 0
    candidate_names: list[str] = Field(default_factory=list)
    diagnostic_message: str = ""


class AdapterDetector:
    """Deterministic, evidence-backed adapter detector and resolver."""

    @staticmethod
    def _load_callable_from_file(file_path: Path, fn_name: str) -> Any:
        """Dynamically and safely imports a Python callable from an isolated file path."""
        module_name = f"beacon_dyn_{file_path.stem}_{hash(str(file_path)) & 0xFFFFFFFF}"
        spec = importlib.util.spec_from_file_location(module_name, str(file_path))
        if not spec or not spec.loader:
            raise ImportError(f"Could not load module spec for '{file_path}'")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        if not hasattr(module, fn_name):
            raise AttributeError(f"Module in '{file_path}' does not contain function '{fn_name}'")
        return getattr(module, fn_name)

    def resolve_adapter_for_repository(
        self,
        analysis: RepositoryAnalysisReport,
        role: Union[AdapterRole, str] = AdapterRole.TARGET,
    ) -> AdapterResolutionResult:
        """Deterministically resolves an ImplementationAdapter from repository analysis facts."""
        role_str = role.value if hasattr(role, "value") else str(role)
        candidates = analysis.entrypoint_candidates
        candidate_names = [f"{c.relative_path}:{c.name}" for c in candidates]

        if not candidates:
            return AdapterResolutionResult(
                status=AdapterResolutionStatus.ADAPTER_UNRESOLVED,
                method="AUTOMATIC",
                role=role_str,
                candidates_count=0,
                candidate_names=[],
                diagnostic_message=(
                    f"Automatic adapter detection failed: No candidate executable entrypoints "
                    f"discovered in repository '{analysis.repository_id}'."
                ),
                detection_evidence={
                    "languages": analysis.languages,
                    "project_structure": analysis.project_structure,
                },
            )

        # Filtering / ranking heuristics:
        # 1. Look for entrypoints with arguments (not 0-arg helpers or main runners)
        valid_candidates = [c for c in candidates if len(c.parameters) > 0 or c.has_type_hints]
        if not valid_candidates:
            valid_candidates = candidates

        # 2. Check if a single candidate matches common root conventions
        primary_match: Optional[DiscoveredEntrypoint] = None
        if len(valid_candidates) == 1:
            primary_match = valid_candidates[0]
        else:
            # Check if one function name directly matches the file stem
            stem_matches = [
                c for c in valid_candidates
                if Path(c.file_path).stem.lower() in c.name.lower() or c.name.lower() in Path(c.file_path).stem.lower()
            ]
            if len(stem_matches) == 1:
                primary_match = stem_matches[0]
            else:
                # Ambiguous: multiple candidates, none uniquely prioritized
                return AdapterResolutionResult(
                    status=AdapterResolutionStatus.ADAPTER_AMBIGUOUS,
                    method="AUTOMATIC",
                    role=role_str,
                    candidates_count=len(valid_candidates),
                    candidate_names=[f"{c.relative_path}:{c.name}" for c in valid_candidates],
                    diagnostic_message=(
                        f"Automatic adapter detection failed: Multiple candidate entrypoints discovered "
                        f"({len(valid_candidates)} candidates) with ambiguous precedence. "
                        f"Failing closed without arbitrary guessing."
                    ),
                    detection_evidence={
                        "candidates": [
                            {"file": c.relative_path, "name": c.name, "params": c.parameters, "line": c.line_number}
                            for c in valid_candidates[:10]
                        ]
                    },
                )

        # Build FunctionAdapter with verified callable
        target_fn = self._load_callable_from_file(Path(primary_match.file_path), primary_match.name)
        adapter_name = f"{primary_match.name}_{role_str}"
        adapter = FunctionAdapter(
            target_fn=target_fn,
            name=adapter_name,
            version=analysis.provenance.resolved_revision or "1.0.0",
            role=role,
            output_normalizer=PreserveCaseNormalizer(),
        )

        return AdapterResolutionResult(
            status=AdapterResolutionStatus.RESOLVED,
            method="AUTOMATIC",
            role=role_str,
            adapter_name=adapter_name,
            resolved_entrypoint=f"{primary_match.relative_path}:{primary_match.name}",
            adapter_instance=adapter,
            candidates_count=len(candidates),
            candidate_names=candidate_names,
            diagnostic_message=f"Deterministically resolved adapter '{adapter_name}' from '{primary_match.relative_path}'.",
            detection_evidence={
                "resolved_file": primary_match.relative_path,
                "resolved_function": primary_match.name,
                "parameters": primary_match.parameters,
                "line_number": primary_match.line_number,
                "has_docstring": bool(primary_match.docstring),
                "commit_sha": analysis.provenance.commit_sha,
                "content_hash": analysis.provenance.content_hash,
            },
        )


adapter_detector = AdapterDetector()
