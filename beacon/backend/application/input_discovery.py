"""BEACON V2 — Input & Benchmark Discovery Engine.

Discovers legitimate test inputs from repository fixtures, test suites,
and matching legitimate benchmark assets. Ensures verifiable provenance for
all discovered inputs. Fails closed with INSUFFICIENT_COVERAGE if no inputs exist.
"""

from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from certification.models import CertificationTestInput
from .repository_service import RepositoryAnalysisReport

logger = logging.getLogger("beacon.application.input_discovery")


class InputDiscoveryStatus(str, Enum):
    """Status of test input discovery operation."""
    SUCCESS = "SUCCESS"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    FAILED = "FAILED"


class InputDiscoveryResult(BaseModel):
    """Result of input and benchmark case discovery."""
    model_config = ConfigDict(extra="ignore")

    status: InputDiscoveryStatus
    inputs_count: int = 0
    test_inputs: list[CertificationTestInput] = Field(default_factory=list)
    discovery_source: str = ""
    discovery_method: str = "AUTOMATIC"
    input_set_hash: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    diagnostic_message: str = ""


class InputDiscoveryEngine:
    """Discovers legitimate evaluation inputs from repository and benchmark sources."""

    def __init__(self):
        self.beacon_root = Path(__file__).resolve().parent.parent.parent

    def discover_inputs(
        self,
        legacy_analysis: RepositoryAnalysisReport,
        modern_analysis: RepositoryAnalysisReport,
        max_cases: int = 100,
    ) -> InputDiscoveryResult:
        """Discovers and resolves canonical test inputs across legacy and modern repositories."""
        discovered_cases: list[dict[str, Any]] = []
        source_desc = ""
        method_desc = "REPOSITORY_FIXTURES"

        # 1. Check if either repository provides explicit input assets (JSON/CSV in repo fixtures/tests/data)
        all_input_assets = legacy_analysis.input_candidates + modern_analysis.input_candidates
        for asset in all_input_assets:
            if asset.sample_values and len(asset.sample_values) > 0:
                try:
                    f_path = Path(asset.file_path)
                    if f_path.exists():
                        raw_data = json.loads(f_path.read_text(encoding="utf-8", errors="ignore"))
                        file_cases = []
                        if isinstance(raw_data, list):
                            file_cases = [item for item in raw_data if isinstance(item, dict)]
                        elif isinstance(raw_data, dict):
                            for k in ("cases", "test_cases", "inputs", "data", "scenarios"):
                                if k in raw_data and isinstance(raw_data[k], list):
                                    file_cases = [item for item in raw_data[k] if isinstance(item, dict)]
                                    break
                            if not file_cases:
                                file_cases = [raw_data]
                        if file_cases:
                            discovered_cases.extend(file_cases)
                            source_desc = f"Repository fixture '{asset.relative_path}'"
                            method_desc = "REPOSITORY_FIXTURE_DISCOVERY"
                            break
                except Exception:
                    pass

        # 2. Check for explicit dataset/manifest inside repository roots
        if not discovered_cases:
            for repo_p_str in [legacy_analysis.provenance.local_path, modern_analysis.provenance.local_path]:
                if not repo_p_str:
                    continue
                repo_p = Path(repo_p_str)
                # Check for explicit benchmark/project manifest
                manifest_file = repo_p / "benchmark_manifest.json"
                if not manifest_file.exists():
                    manifest_file = repo_p / "beacon_manifest.json"
                if manifest_file.exists():
                    try:
                        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8", errors="ignore"))
                        ds_rel = manifest_data.get("dataset_path") or manifest_data.get("dataset_file")
                        if ds_rel:
                            ds_file = (repo_p / ds_rel).resolve()
                            if ds_file.exists() and ds_file.is_file() and ds_file.suffix == ".json":
                                ds_raw = json.loads(ds_file.read_text(encoding="utf-8", errors="ignore"))
                                if isinstance(ds_raw, list):
                                    discovered_cases.extend([d for d in ds_raw if isinstance(d, dict)])
                                elif isinstance(ds_raw, dict):
                                    for k in ("test_cases", "cases", "inputs", "data"):
                                        if k in ds_raw and isinstance(ds_raw[k], list):
                                            discovered_cases.extend([d for d in ds_raw[k] if isinstance(d, dict)])
                                            break
                                if discovered_cases:
                                    source_desc = f"Explicit repository manifest '{manifest_file.name}' -> '{ds_rel}'"
                                    method_desc = "EXPLICIT_MANIFEST_DISCOVERY"
                                    break
                    except Exception:
                        pass

                # Check legitimate repo dataset subdirectory (e.g. repo/dataset/*.json)
                ds_dir = repo_p / "dataset"
                if not discovered_cases and ds_dir.exists() and ds_dir.is_dir():
                    for jf in sorted(ds_dir.glob("*.json")):
                        if jf.stem.lower() == "validation":
                            continue
                        try:
                            ds_raw = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
                            cases = []
                            if isinstance(ds_raw, list):
                                cases = [d for d in ds_raw if isinstance(d, dict)]
                            elif isinstance(ds_raw, dict):
                                for k in ("test_cases", "scenarios", "cases", "data", "inputs"):
                                    if k in ds_raw and isinstance(ds_raw[k], list):
                                        cases = [d for d in ds_raw[k] if isinstance(d, dict)]
                                        break
                                if not cases:
                                    cases = [ds_raw]
                            if cases:
                                discovered_cases.extend(cases)
                                source_desc = f"Repository dataset directory '{jf.name}'"
                                method_desc = "REPOSITORY_DATASET_DISCOVERY"
                                break
                        except Exception:
                            pass
                if discovered_cases:
                    break

        # 2b. Check for authoritative code-defined transaction scenarios (e.g. CardDemo run_vector scenarios)
        if not discovered_cases:
            for repo_p_str in [legacy_analysis.provenance.local_path, modern_analysis.provenance.local_path]:
                if not repo_p_str:
                    continue
                repo_p = Path(repo_p_str)
                py_candidates = [repo_p] if repo_p.is_file() and repo_p.suffix == ".py" else list(repo_p.rglob("*.py"))
                for py_f in py_candidates:
                    try:
                        src_text = py_f.read_text(encoding="utf-8", errors="ignore")
                        if "run_vector" in src_text or "scenario" in src_text.lower():
                            scenarios = re.findall(r'(?:scenario|SCENARIO)\s*==\s*["\']([A-Z0-9_]+)["\']', src_text)
                            if scenarios:
                                seen_scenarios = set()
                                for sc in scenarios:
                                    if sc not in seen_scenarios:
                                        seen_scenarios.add(sc)
                                        discovered_cases.append({"SCENARIO": sc})
                                if discovered_cases:
                                    source_desc = f"Authoritative transaction scenarios from '{py_f.name}'"
                                    method_desc = "CODE_DEFINED_SCENARIO_DISCOVERY"
                                    break
                    except Exception:
                        pass
                if discovered_cases:
                    break

        # 3. Fail closed if zero legitimate inputs found — NEVER manufacture synthetic data!
        if not discovered_cases:
            return InputDiscoveryResult(
                status=InputDiscoveryStatus.INSUFFICIENT_COVERAGE,
                inputs_count=0,
                test_inputs=[],
                discovery_source="",
                discovery_method="FAILED",
                diagnostic_message=(
                    "Input discovery failed: No legitimate test cases or fixtures could be discovered "
                    "in the provided repositories. Synthetic fallback is strictly disabled in BEACON V2. "
                    "Failing closed with INSUFFICIENT_COVERAGE."
                ),
            )

        # 4. Input Validation: Validate cases against discovered entrypoint parameters
        expected_params = []
        if legacy_analysis.entrypoint_candidates:
            expected_params = legacy_analysis.entrypoint_candidates[0].parameters

        validated_cases: list[dict[str, Any]] = []
        for case in discovered_cases:
            if not isinstance(case, dict):
                continue
            # If expected parameters exist, verify at least one matches or case has fields
            if expected_params and len(expected_params) > 0:
                if any(p in case for p in expected_params):
                    validated_cases.append(case)
                elif len(case) > 0:
                    # Pass through if non-empty dictionary
                    validated_cases.append(case)
            else:
                validated_cases.append(case)

        if not validated_cases:
            return InputDiscoveryResult(
                status=InputDiscoveryStatus.INSUFFICIENT_COVERAGE,
                inputs_count=0,
                test_inputs=[],
                discovery_source=source_desc,
                discovery_method="VALIDATION_FAILED",
                diagnostic_message=(
                    f"Input discovery failed: Discovered inputs from '{source_desc}' failed validation "
                    f"against entrypoint parameters {expected_params}."
                ),
            )

        discovered_cases = validated_cases

        # Slice to max_cases
        selected_cases = discovered_cases[:max_cases]

        # Convert to canonical CertificationTestInput with cryptographic provenance
        test_inputs: list[CertificationTestInput] = []
        for idx, c_dict in enumerate(selected_cases):
            canonical_json = json.dumps(c_dict, sort_keys=True, separators=(",", ":"), default=str)
            inp_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
            inp_id = f"INP-{idx+1:04d}-{inp_hash[:8]}"
            test_inputs.append(
                CertificationTestInput(
                    input_id=inp_id,
                    values=c_dict,
                    metadata={"source": source_desc, "index": idx + 1},
                    provenance={
                        "discovery_method": method_desc,
                        "source": source_desc,
                        "input_hash": inp_hash,
                    },
                )
            )

        # Compute overall input set canonical hash
        all_hashes = "".join(inp.provenance.get("input_hash", "") for inp in test_inputs)
        input_set_hash = hashlib.sha256(all_hashes.encode("utf-8")).hexdigest()

        return InputDiscoveryResult(
            status=InputDiscoveryStatus.SUCCESS,
            inputs_count=len(test_inputs),
            test_inputs=test_inputs,
            discovery_source=source_desc,
            discovery_method=method_desc,
            input_set_hash=input_set_hash,
            provenance={
                "source": source_desc,
                "discovery_method": method_desc,
                "input_set_hash": input_set_hash,
                "count": len(test_inputs),
            },
            diagnostic_message=f"Discovered {len(test_inputs)} authoritative test cases via {method_desc}.",
        )


input_discovery_engine = InputDiscoveryEngine()
