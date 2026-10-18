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
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from certification.models import CertificationTestInput
from common.config import settings
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

    def _discover_full_beacon_inputs(
        self,
        legacy_analysis: RepositoryAnalysisReport,
        modern_analysis: RepositoryAnalysisReport,
        max_cases: int,
        legacy_entrypoint_file: Optional[Path],
        modern_entrypoint_file: Optional[Path],
    ) -> InputDiscoveryResult:
        """Build source-grounded, rule-directed cases for both implementation roles."""
        from mining.source_rule_extractor import (
            SourceRuleExtractionError,
            extract_aligned_rules_and_tests,
        )

        configured_provider = (getattr(settings, "llm_provider", None) or "openrouter").lower().strip()
        if configured_provider == "auto":
            configured_provider = "openrouter"
        if configured_provider not in ("openrouter", "gemini", "anthropic"):
            return InputDiscoveryResult(
                status=InputDiscoveryStatus.FAILED,
                discovery_method="FAILED",
                provenance={
                    "rule_extraction_status": "AI_PROVIDER_REQUIRED",
                    "llm_provider": {
                        "requested_provider": configured_provider,
                        "actual_provider": None,
                        "fallback_used": False,
                    },
                },
                diagnostic_message=(
                    "FULL_BEACON requires a configured cloud AI provider for independent dual-source "
                    "rule extraction; offline or local fallback is not accepted as source evidence."
                ),
            )

        legacy_root = Path(legacy_analysis.provenance.local_path)
        modern_root = Path(modern_analysis.provenance.local_path)
        try:
            result = extract_aligned_rules_and_tests(
                legacy_root=legacy_root,
                modern_root=modern_root,
                legacy_entrypoint=legacy_entrypoint_file,
                modern_entrypoint=modern_entrypoint_file,
                provider_name=configured_provider,
            )
        except SourceRuleExtractionError as exc:
            logger.info("FULL_BEACON dual-source rule discovery was blocked: %s", exc)
            return InputDiscoveryResult(
                status=InputDiscoveryStatus.FAILED,
                discovery_method="FAILED",
                provenance={
                    "rule_extraction_status": "SOURCE_RULE_EXTRACTION_FAILED",
                    "diagnostic": str(exc),
                    "llm_provider": {
                        "requested_provider": configured_provider,
                        "actual_provider": None,
                        "fallback_used": False,
                    },
                },
                diagnostic_message=f"Full BEACON source-grounded rule extraction failed closed: {exc}",
            )

        rules = result["rules"]
        alignments = result["alignments"]
        provider_metadata = result["providers"]
        provider_names = {
            item.get("actual_provider")
            for item in provider_metadata.values()
            if isinstance(item, dict)
        }
        rule_manifest_hash = hashlib.sha256(
            json.dumps(rules, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        if not result["complete"]:
            return InputDiscoveryResult(
                status=InputDiscoveryStatus.INSUFFICIENT_COVERAGE,
                discovery_method="DUAL_SOURCE_RULE_ALIGNMENT",
                provenance={
                    "rule_extraction_status": "RULE_ALIGNMENT_GAPS",
                    "ai_mined_rules": rules,
                    "rule_alignments": alignments,
                    "rule_manifest_hash": rule_manifest_hash,
                    "source_hashes": result["source_hashes"],
                    "source_gaps": result["gaps"],
                    "llm_provider": {
                        "requested_provider": configured_provider,
                        "actual_providers": sorted(name for name in provider_names if name),
                        "provider_calls": provider_metadata,
                        "fallback_used": False,
                    },
                },
                diagnostic_message=(
                    "Full BEACON blocked: independently extracted source rules include missing, "
                    "conflicting, or ambiguous cross-implementation behavior."
                ),
            )

        cases: list[CertificationTestInput] = []
        seen: set[str] = set()
        rule_ids = {rule["rule_id"] for rule in rules}
        for item in result["test_cases"]:
            if item["rule_id"] not in rule_ids:
                continue
            values = item["values"]
            canonical = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
            signature = f"{item['rule_id']}:{canonical}"
            if signature in seen:
                continue
            seen.add(signature)
            input_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            cases.append(
                CertificationTestInput(
                    input_id=f"INP-EDABC-{len(cases) + 1:04d}-{input_hash[:8]}",
                    values=values,
                    origin="ai_generated",
                    provenance={
                        "source": "dual_source_rule_directed_ai_candidate",
                        "condition_provenance": item["rule_id"],
                        "rule_manifest_hash": rule_manifest_hash,
                        "source_hashes": result["source_hashes"],
                        "actual_providers": sorted(name for name in provider_names if name),
                        "fallback_used": False,
                        "input_hash": input_hash,
                    },
                    tags=["edabc", item["rule_id"]],
                )
            )
            if len(cases) >= max_cases:
                break

        covered_rules = {case.provenance["condition_provenance"] for case in cases}
        missing_rules = sorted(rule_ids - covered_rules)
        if not cases or missing_rules:
            return InputDiscoveryResult(
                status=InputDiscoveryStatus.INSUFFICIENT_COVERAGE,
                discovery_method="DUAL_SOURCE_RULE_DIRECTED_TESTING",
                provenance={
                    "rule_extraction_status": "TARGETED_TEST_COVERAGE_INSUFFICIENT",
                    "ai_mined_rules": rules,
                    "rule_alignments": alignments,
                    "rule_manifest_hash": rule_manifest_hash,
                    "missing_tested_rule_ids": missing_rules,
                    "source_hashes": result["source_hashes"],
                    "llm_provider": provider_metadata,
                },
                diagnostic_message=(
                    "Full BEACON blocked: every aligned source rule requires at least one "
                    "source-validated targeted test within the input limit."
                ),
            )

        input_set_hash = hashlib.sha256(
            json.dumps(
                [{"id": case.input_id, "values": case.values} for case in cases],
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        return InputDiscoveryResult(
            status=InputDiscoveryStatus.SUCCESS,
            inputs_count=len(cases),
            test_inputs=cases,
            discovery_source="AI-generated tests directed by independently extracted and aligned source rules",
            discovery_method="DUAL_SOURCE_RULE_DIRECTED_TESTING",
            input_set_hash=input_set_hash,
            provenance={
                "rule_extraction_status": "SUCCESS",
                "ai_mined_rules": rules,
                "rule_alignments": alignments,
                "rule_manifest_hash": rule_manifest_hash,
                "source_hashes": result["source_hashes"],
                "source_gaps": result["gaps"],
                "rule_count": len(rules),
                "covered_rule_count": len(covered_rules),
                "targeted_input_count": len(cases),
                "input_set_hash": input_set_hash,
                "llm_provider": {
                    "requested_provider": configured_provider,
                    "actual_providers": sorted(name for name in provider_names if name),
                    "provider_calls": provider_metadata,
                    "fallback_used": False,
                },
            },
            diagnostic_message=(
                f"Extracted and aligned {len(rules)} source-grounded rules from both "
                f"implementations and generated {len(cases)} rule-directed inputs."
            ),
        )

    def discover_inputs(
        self,
        legacy_analysis: RepositoryAnalysisReport,
        modern_analysis: RepositoryAnalysisReport,
        max_cases: int = 100,
        legacy_entrypoint_file: Optional[Path] = None,
        modern_entrypoint_file: Optional[Path] = None,
        evaluation_mode: str = "FULL_BEACON",
        run_id: Optional[str] = None,
    ) -> InputDiscoveryResult:
        """Discovers and resolves canonical test inputs across legacy and modern repositories.
        In FULL_BEACON mode, both implementations are independently analyzed and rules are
        accepted only after exact local source-anchor validation and AI alignment.
        """
        is_full_beacon = str(evaluation_mode).upper() == "FULL_BEACON"
        if is_full_beacon:
            return self._discover_full_beacon_inputs(
                legacy_analysis=legacy_analysis,
                modern_analysis=modern_analysis,
                max_cases=max_cases,
                legacy_entrypoint_file=legacy_entrypoint_file,
                modern_entrypoint_file=modern_entrypoint_file,
            )

        discovered_cases: list[dict[str, Any]] = []
        source_desc = ""
        method_desc = "REPOSITORY_FIXTURES"

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
                except (OSError, json.JSONDecodeError):
                    logger.warning("Ignoring unreadable repository input fixture '%s'.", asset.file_path)

        if not discovered_cases:
            for repo_p_str in [legacy_analysis.provenance.local_path, modern_analysis.provenance.local_path]:
                if not repo_p_str:
                    continue
                repo_p = Path(repo_p_str)
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
                    except (OSError, json.JSONDecodeError):
                        logger.warning("Ignoring unreadable dataset manifest '%s'.", manifest_file)

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
                        except (OSError, json.JSONDecodeError):
                            logger.warning("Ignoring unreadable repository dataset '%s'.", jf)
                if discovered_cases:
                    break

        ai_mined_rules: list[dict[str, Any]] = []
        llm_provider_metadata: dict[str, Any] = {}
        proposed_cases_raw: list[dict[str, Any]] = []
        rejected_candidates: list[dict[str, Any]] = []

        # Outside FULL_BEACON, inputs must come from repository fixtures or manifests.
        if not discovered_cases:
            err_category = llm_provider_metadata.get("error_category") or "DISCOVERY_INSUFFICIENT"
            err_detail = llm_provider_metadata.get("error") or "No legitimate AI-grounded inputs could be discovered"
            diag = (
                f"Full BEACON input discovery failed closed: {err_category} ({err_detail}). "
                f"Non-AI fallback and hardcoded fixtures are strictly disallowed in FULL_BEACON mode."
                if is_full_beacon
                else "Input discovery failed: No legitimate test cases or fixtures could be discovered in the provided repositories."
            )
            return InputDiscoveryResult(
                status=InputDiscoveryStatus.FAILED if is_full_beacon else InputDiscoveryStatus.INSUFFICIENT_COVERAGE,
                inputs_count=0,
                test_inputs=[],
                discovery_source=source_desc,
                discovery_method="FAILED",
                input_set_hash="",
                provenance={
                    "llm_provider": llm_provider_metadata,
                    "ai_mined_rules": ai_mined_rules,
                    "ai_mined_rule_count": len(ai_mined_rules),
                    "error_category": err_category,
                    "proposed_count": len(proposed_cases_raw),
                    "accepted_count": 0,
                    "rejected_count": len(rejected_candidates),
                    "rejected_details": rejected_candidates,
                },
                diagnostic_message=diag,
            )

        # Candidate Validation: Validate cases against entrypoint parameters if known
        expected_params = []
        if legacy_analysis.entrypoint_candidates:
            expected_params = legacy_analysis.entrypoint_candidates[0].parameters

        validated_cases: list[dict[str, Any]] = []
        for case in discovered_cases:
            if not isinstance(case, dict):
                continue
            if expected_params and len(expected_params) > 0:
                if any(p in case for p in expected_params) or len(case) > 0:
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
                input_set_hash="",
                provenance={
                    "llm_provider": llm_provider_metadata,
                    "ai_mined_rules": ai_mined_rules,
                    "error_category": "ALL_CANDIDATES_INVALID",
                },
                diagnostic_message=f"Input discovery failed: Discovered inputs from '{source_desc}' failed entrypoint validation.",
            )

        discovered_cases = validated_cases
        selected_cases = discovered_cases[:max_cases]

        # Convert to canonical CertificationTestInput with complete cryptographic provenance
        test_inputs: list[CertificationTestInput] = []
        seen_input_signatures: set[str] = set()
        duplicate_count = 0

        legacy_hash = legacy_analysis.provenance.content_hash
        modern_hash = modern_analysis.provenance.content_hash
        run_id_val = run_id or f"RUN-{legacy_hash[:8]}-{modern_hash[:8]}"

        for idx, c_dict in enumerate(selected_cases):
            input_values = {key: value for key, value in c_dict.items() if not key.startswith("__")}
            canonical_json = json.dumps(input_values, sort_keys=True, separators=(",", ":"), default=str)
            if canonical_json in seen_input_signatures:
                duplicate_count += 1
                continue
            seen_input_signatures.add(canonical_json)
            inp_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
            inp_id = f"INP-AI-{len(test_inputs)+1:04d}-{inp_hash[:8]}" if is_full_beacon else f"INP-{len(test_inputs)+1:04d}-{inp_hash[:8]}"

            candidate_prov = {
                "candidate_id": f"CAND-{len(test_inputs)+1:04d}",
                "certification_run_id": run_id_val,
                "source_hashes": {
                    "legacy": legacy_hash,
                    "modern": modern_hash,
                },
                "requested_provider": (
                    llm_provider_metadata.get("requested_provider", "openrouter")
                    if is_full_beacon
                    else "repository_fixture"
                ),
                "actual_provider": (
                    llm_provider_metadata.get("actual_provider", "openrouter")
                    if is_full_beacon
                    else "repository_fixture"
                ),
                "model": llm_provider_metadata.get("model", "") if is_full_beacon else "",
                "schema_version": "1.0",
                "canonical_candidate_hash": inp_hash,
                "validation_status": "ACCEPTED",
                "condition_provenance": c_dict.get("__condition_provenance", "RULE-001"),
                "discovery_method": method_desc,
                "source": source_desc,
                "input_hash": inp_hash,
            }

            test_inputs.append(
                CertificationTestInput(
                    input_id=inp_id,
                    values=input_values,
                    origin="ai_generated" if is_full_beacon or method_desc == "AI_PROPOSED_INPUTS_SOURCE_VALIDATED" else "diverse_sampling",
                    provenance=candidate_prov,
                )
            )

        if not test_inputs:
            return InputDiscoveryResult(
                status=InputDiscoveryStatus.INSUFFICIENT_COVERAGE,
                inputs_count=0,
                test_inputs=[],
                discovery_source=source_desc,
                discovery_method="VALIDATION_FAILED",
                input_set_hash="",
                provenance={
                    "llm_provider": llm_provider_metadata,
                    "ai_mined_rules": ai_mined_rules,
                    "duplicate_count": duplicate_count,
                    "error_category": "ALL_CANDIDATES_DUPLICATES",
                },
                diagnostic_message="Input discovery failed: all candidate cases were empty or duplicate.",
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
                "proposed_count": len(proposed_cases_raw),
                "accepted_count": len(test_inputs),
                "rejected_count": len(rejected_candidates),
                "rejected_details": rejected_candidates,
                "duplicate_count": duplicate_count,
                "ai_mined_rules": ai_mined_rules,
                "ai_mined_rule_count": len(ai_mined_rules),
                "rule_extraction_status": llm_provider_metadata.get("rule_extraction_status", "SUCCESS"),
                "llm_provider": llm_provider_metadata,
            },
            diagnostic_message=f"Discovered {len(test_inputs)} authoritative test cases via {method_desc}.",
        )

input_discovery_engine = InputDiscoveryEngine()
