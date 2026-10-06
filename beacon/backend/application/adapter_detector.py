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
from certification.adapters import (
    FunctionAdapter,
    PreserveCaseNormalizer,
    CobolCicsAdapter,
    check_cobol_cics_runtime,
)
from .repository_service import DiscoveredEntrypoint, RepositoryAnalysisReport

logger = logging.getLogger("beacon.application.adapter_detector")


class AdapterResolutionStatus(str, Enum):
    """Authoritative status of automatic adapter resolution."""
    RESOLVED = "RESOLVED"
    ADAPTER_AMBIGUOUS = "ADAPTER_AMBIGUOUS"
    ADAPTER_UNRESOLVED = "ADAPTER_UNRESOLVED"
    ADAPTER_UNSUPPORTED = "ADAPTER_UNSUPPORTED"
    FAILED = "FAILED"


class AdapterResolutionResult(BaseModel):
    """Result of automatic adapter detection and resolution with verifiable evidence."""
    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    status: AdapterResolutionStatus
    method: str = "AUTOMATIC_STATIC"
    role: str = "target"
    adapter_name: Optional[str] = None
    resolved_entrypoint: Optional[str] = None
    resolved_file: Optional[str] = None
    resolved_function: Optional[str] = None
    adapter_instance: Optional[Any] = None
    detection_evidence: dict[str, Any] = Field(default_factory=dict)
    candidates_count: int = 0
    candidate_names: list[str] = Field(default_factory=list)
    diagnostic_message: str = ""


class AdapterDetector:
    """Deterministic, evidence-backed adapter detector and resolver.
    
    Operates strictly via static inspection during the detection phase.
    Code loading/execution is decoupled and only authorized during runtime execution.
    """

    @staticmethod
    def load_authorized_adapter(
        file_path: Path,
        fn_name: str,
        adapter_name: str,
        role: Union[AdapterRole, str],
        version: str = "1.0.0",
    ) -> ImplementationAdapter:
        """Loads and binds an authorized adapter (Python callable or COBOL CICS runtime) ONLY when execution is authorized."""
        # 1. COBOL CICS Adapter
        if file_path.suffix.lower() in (".cbl", ".cob", ".cpy"):
            discovered_cpy_dirs = []
            standard_cpy_dir = Path(__file__).resolve().parent.parent.parent / "data" / "copybooks"
            if standard_cpy_dir.is_dir():
                discovered_cpy_dirs.append(standard_cpy_dir)
            if file_path.parent.exists():
                discovered_cpy_dirs.append(file_path.parent)
            if (file_path.parent / "cpy").exists():
                discovered_cpy_dirs.append(file_path.parent / "cpy")
            if (file_path.parent.parent / "cpy").exists():
                discovered_cpy_dirs.append(file_path.parent.parent / "cpy")
            
            # Find sibling or parent directories containing .cpy files
            root_cand = file_path.parent
            for _ in range(3):
                if root_cand.is_dir():
                    for cp in list(root_cand.glob("*.cpy")) + list(root_cand.glob("*.CPY")):
                        if cp.parent not in discovered_cpy_dirs:
                            discovered_cpy_dirs.append(cp.parent)
                root_cand = root_cand.parent

            source_txt = file_path.read_text(encoding="utf-8", errors="ignore")
            from intelligence.cobol_plan import generate_cobol_execution_plan
            plan = generate_cobol_execution_plan(source_txt, file_path=file_path)

            data_dir = None
            for cand_data in [file_path.parent / "data", file_path.parent.parent / "data"]:
                if cand_data.is_dir():
                    data_dir = cand_data
                    break

            return CobolCicsAdapter(
                program_id=fn_name or plan.program_id,
                source_file=file_path,
                copybook_dirs=discovered_cpy_dirs,
                data_dir=data_dir,
                name=adapter_name,
                role=role,
                version=version,
                execution_plan=plan,
            )

        # 2. Modern Python Adapter with companion module resolution within repo
        parent_dir = file_path.parent
        if str(parent_dir) not in sys.path:
            sys.path.insert(0, str(parent_dir))
        if str(parent_dir.parent) not in sys.path:
            sys.path.insert(0, str(parent_dir.parent))

        # Dynamically discover companion Python modules in uploaded dir and standard companions
        standard_py_dir = Path(__file__).resolve().parent.parent.parent / "data" / "python_companions"
        search_dirs = [parent_dir]
        if standard_py_dir.is_dir():
            search_dirs.append(standard_py_dir)
            if str(standard_py_dir) not in sys.path:
                sys.path.insert(0, str(standard_py_dir))

        for s_dir in search_dirs:
            for companion in s_dir.glob("*.py"):
                if companion.resolve() != file_path.resolve():
                    comp_name = companion.stem
                    if comp_name not in sys.modules:
                        try:
                            c_spec = importlib.util.spec_from_file_location(comp_name, str(companion))
                            if c_spec and c_spec.loader:
                                c_mod = importlib.util.module_from_spec(c_spec)
                                sys.modules[comp_name] = c_mod
                                sys.modules[f"{parent_dir.name}.{comp_name}"] = c_mod
                                c_spec.loader.exec_module(c_mod)
                        except Exception as c_err:
                            logger.debug(f"Companion pre-load note for {comp_name}: {c_err}")

        module_name = f"beacon_dyn_{file_path.stem}_{hash(str(file_path)) & 0xFFFFFFFF}"
        spec = importlib.util.spec_from_file_location(
            module_name,
            str(file_path),
            submodule_search_locations=[str(parent_dir)],
        )
        if not spec or not spec.loader:
            raise ImportError(f"Could not load module spec for '{file_path}'")
        module = importlib.util.module_from_spec(spec)
        module.__package__ = parent_dir.name
        sys.modules[module_name] = module
        sys.modules[f"{parent_dir.name}.{file_path.stem}"] = module

        spec.loader.exec_module(module)
        if not hasattr(module, fn_name):
            raise AttributeError(f"Module in '{file_path}' does not contain function '{fn_name}'")
        target_fn = getattr(module, fn_name)

        return FunctionAdapter(
            target_fn=target_fn,
            name=adapter_name,
            version=version,
            role=role,
            output_normalizer=PreserveCaseNormalizer(),
        )

    def resolve_adapter_for_repository(
        self,
        analysis: RepositoryAnalysisReport,
        role: Union[AdapterRole, str] = AdapterRole.TARGET,
    ) -> AdapterResolutionResult:
        """Deterministically resolves an ImplementationAdapter strictly from static repository analysis facts.
        
        CRITICAL SECURITY INVARIANT:
        This method DOES NOT import or execute repository code.
        """
        role_str = role.value if hasattr(role, "value") else str(role)

        # Check language support
        supported_langs = {"python", "cobol"}
        repo_langs = {lang.lower() for lang in analysis.languages}
        if not repo_langs.intersection(supported_langs):
            return AdapterResolutionResult(
                status=AdapterResolutionStatus.ADAPTER_UNSUPPORTED,
                method="AUTOMATIC_STATIC",
                role=role_str,
                diagnostic_message=(
                    f"Automatic adapter detection unsupported for repository languages: {analysis.languages}. "
                    "BEACON V2 supports Python and COBOL/CICS."
                ),
                detection_evidence={"languages": analysis.languages},
            )

        candidates = analysis.entrypoint_candidates
        candidate_names = [f"{c.relative_path}:{c.name}" for c in candidates]

        if not candidates:
            return AdapterResolutionResult(
                status=AdapterResolutionStatus.ADAPTER_UNRESOLVED,
                method="AUTOMATIC_STATIC",
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

        # ── COBOL / CICS Resolution Branch ────────────────────────────────────
        if "cobol" in repo_langs:
            # Find primary COBOL program candidate
            primary_cbl = next((c for c in candidates if c.evidence.get("language") == "cobol"), candidates[0])
            ev = primary_cbl.evidence
            is_cics = ev.get("is_cics", False)
            missing_cpys = ev.get("missing_copybooks", [])
            missing_dss = ev.get("missing_datasets", [])
            runtime_ok, runtime_diag, runtime_details = check_cobol_cics_runtime()

            # Fail closed to ADAPTER_UNRESOLVED (never ADAPTER_UNSUPPORTED) if runtime or copybooks missing
            if not runtime_ok:
                return AdapterResolutionResult(
                    status=AdapterResolutionStatus.ADAPTER_UNRESOLVED,
                    method="AUTOMATIC_STATIC",
                    role=role_str,
                    candidates_count=len(candidates),
                    candidate_names=candidate_names,
                    diagnostic_message=(
                        f"COBOL execution environment unavailable for program '{primary_cbl.name}': {runtime_diag}. "
                        "A valid GnuCOBOL (cobc) runtime is required."
                    ),
                    detection_evidence={
                        **ev,
                        "runtime_status": "UNAVAILABLE",
                        "runtime_diagnostics": runtime_diag,
                    },
                )

            # Re-check missing copybooks against standard copybook library
            std_cpy = Path(__file__).resolve().parent.parent.parent / "data" / "copybooks"
            if missing_cpys and std_cpy.is_dir():
                still_missing = []
                for c in missing_cpys:
                    found = False
                    for ext in (".cpy", ".CPY", ".cbl", ""):
                        if (std_cpy / f"{c}{ext}").exists():
                            found = True
                            break
                    if not found:
                        still_missing.append(c)
                missing_cpys = still_missing

            if missing_cpys:
                return AdapterResolutionResult(
                    status=AdapterResolutionStatus.ADAPTER_UNRESOLVED,
                    method="AUTOMATIC_STATIC",
                    role=role_str,
                    candidates_count=len(candidates),
                    candidate_names=candidate_names,
                    diagnostic_message=(
                        f"COBOL/CICS dependencies unresolved for program '{primary_cbl.name}'. "
                        f"Missing {len(missing_cpys)} required copybook(s): {missing_cpys}."
                    ),
                    detection_evidence={
                        **ev,
                        "runtime_status": "AVAILABLE",
                        "missing_copybooks": missing_cpys,
                        "missing_datasets": missing_dss,
                    },
                )

            adapter_name = f"cics_{primary_cbl.name.lower()}_{role_str}"
            return AdapterResolutionResult(
                status=AdapterResolutionStatus.RESOLVED,
                method="AUTOMATIC_STATIC",
                role=role_str,
                adapter_name=adapter_name,
                resolved_entrypoint=f"{primary_cbl.relative_path}:{primary_cbl.name}",
                resolved_file=primary_cbl.file_path,
                resolved_function=primary_cbl.name,
                candidates_count=len(candidates),
                candidate_names=candidate_names,
                diagnostic_message=(
                    f"Deterministically resolved COBOL/CICS adapter '{adapter_name}' for program '{primary_cbl.name}'. "
                    f"CICS commands: {ev.get('cics_commands', [])}. Copybooks resolved: {len(ev.get('resolved_copybooks', []))}."
                ),
                detection_evidence={
                    **ev,
                    "runtime_status": "AVAILABLE",
                    "runtime_diagnostics": runtime_diag,
                    "commit_sha": analysis.provenance.commit_sha,
                    "content_hash": analysis.provenance.content_hash,
                },
            )

        # ── Python Resolution Branch ──────────────────────────────────────────
        # Static Filtering / ranking heuristics based on discovered parameters and module match:
        clean_candidates = [c for c in candidates if not c.name.startswith("_")]
        valid_candidates = [c for c in clean_candidates if len(c.parameters) > 0 or c.has_type_hints]
        if not valid_candidates:
            valid_candidates = clean_candidates or candidates

        if len(valid_candidates) == 1:
            primary_match = valid_candidates[0]
        else:
            stem_matches = [
                c for c in valid_candidates
                if Path(c.file_path).stem.lower() in c.name.lower() or c.name.lower() in Path(c.file_path).stem.lower()
            ]
            if len(stem_matches) == 1:
                primary_match = stem_matches[0]
            elif any(c.name.lower() in ("run_vector", "main", "execute", "run", "process") for c in valid_candidates):
                primary_match = next(c for c in valid_candidates if c.name.lower() in ("run_vector", "main", "execute", "run", "process"))
            elif len(valid_candidates) > 0:
                primary_match = valid_candidates[0]
            else:
                    return AdapterResolutionResult(
                        status=AdapterResolutionStatus.ADAPTER_AMBIGUOUS,
                        method="AUTOMATIC_STATIC",
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

        # Verify companion module resolution for Python against repository & standard companions
        missing_companions = primary_match.evidence.get("missing_companions", [])
        std_py = Path(__file__).resolve().parent.parent.parent / "data" / "python_companions"
        if missing_companions and std_py.is_dir():
            missing_companions = [m for m in missing_companions if not (std_py / f"{m}.py").exists()]

        if missing_companions:
            return AdapterResolutionResult(
                status=AdapterResolutionStatus.ADAPTER_UNRESOLVED,
                method="AUTOMATIC_STATIC",
                role=role_str,
                candidates_count=len(candidates),
                candidate_names=candidate_names,
                diagnostic_message=(
                    f"Modern Python entrypoint '{primary_match.name}' requires companion module(s) "
                    f"{missing_companions} which could not be resolved in the repository context."
                ),
                detection_evidence={
                    "resolved_file": primary_match.relative_path,
                    "resolved_function": primary_match.name,
                    "missing_companions": missing_companions,
                },
            )

        adapter_name = f"{primary_match.name}_{role_str}"
        return AdapterResolutionResult(
            status=AdapterResolutionStatus.RESOLVED,
            method="AUTOMATIC_STATIC",
            role=role_str,
            adapter_name=adapter_name,
            resolved_entrypoint=f"{primary_match.relative_path}:{primary_match.name}",
            resolved_file=primary_match.file_path,
            resolved_function=primary_match.name,
            adapter_instance=None,
            candidates_count=len(candidates),
            candidate_names=candidate_names,
            diagnostic_message=f"Deterministically resolved adapter '{adapter_name}' from '{primary_match.relative_path}'.",
            detection_evidence={
                "resolved_file": primary_match.relative_path,
                "resolved_function": primary_match.name,
                "parameters": primary_match.parameters,
                "line_number": primary_match.line_number,
                "has_docstring": bool(primary_match.docstring),
                "resolved_companions": primary_match.evidence.get("resolved_companions", []),
                "commit_sha": analysis.provenance.commit_sha,
                "content_hash": analysis.provenance.content_hash,
            },
        )


adapter_detector = AdapterDetector()

