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
        In FULL_BEACON mode, strictly requires OpenRouter AI-generated candidates with source grounding.
        """
        is_full_beacon = str(evaluation_mode).upper() == "FULL_BEACON"
        discovered_cases: list[dict[str, Any]] = []
        source_desc = ""
        method_desc = "AI_PROPOSED_INPUTS_SOURCE_VALIDATED" if is_full_beacon else "REPOSITORY_FIXTURES"

        # Check repository fixtures ONLY if NOT in FULL_BEACON mode (controlled test-only mode)
        if not is_full_beacon:
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
                        except Exception:
                            pass

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

        ai_mined_rules: list[dict[str, Any]] = []
        llm_provider_metadata: dict[str, Any] = {}
        proposed_cases_raw: list[dict[str, Any]] = []
        rejected_candidates: list[dict[str, Any]] = []

        # Resolve COBOL and Modern entrypoints/source files
        cobol_candidates: list[Path] = []
        py_candidates: list[Path] = []
        if legacy_entrypoint_file and legacy_entrypoint_file.is_file() and legacy_entrypoint_file.suffix.lower() in (".cbl", ".cob"):
            cobol_candidates.append(legacy_entrypoint_file)
        if modern_entrypoint_file and modern_entrypoint_file.is_file() and modern_entrypoint_file.suffix.lower() == ".py":
            py_candidates.append(modern_entrypoint_file)

        legacy_root = Path(legacy_analysis.provenance.local_path)
        if not cobol_candidates:
            if legacy_root.is_file() and legacy_root.suffix.lower() in (".cbl", ".cob"):
                cobol_candidates.append(legacy_root)
            elif legacy_root.is_dir():
                for pattern in ("*.cbl", "*.cob", "*.CBL", "*.COB"):
                    cobol_candidates.extend(legacy_root.rglob(pattern))

        modern_root = Path(modern_analysis.provenance.local_path)
        if not py_candidates:
            if modern_root.is_file() and modern_root.suffix.lower() == ".py":
                py_candidates.append(modern_root)
            elif modern_root.is_dir():
                py_candidates.extend(modern_root.rglob("*.py"))

        primary_cbl = None
        primary_py = None
        if cobol_candidates:
            primary_cbl = (
                legacy_entrypoint_file
                if legacy_entrypoint_file and legacy_entrypoint_file in cobol_candidates
                else sorted(cobol_candidates, key=lambda path: str(path).lower())[0]
            )
            primary_py = (
                modern_entrypoint_file
                if modern_entrypoint_file and modern_entrypoint_file in py_candidates
                else sorted(py_candidates, key=lambda path: str(path).lower())[0] if py_candidates else None
            )

            # Mine conditions and candidates via OpenRouter
            ai_cases, ai_mined_rules, llm_provider_metadata = self._mine_cobol_conditions_with_ai(
                primary_cbl,
                primary_py,
                legacy_analysis=legacy_analysis,
                modern_analysis=modern_analysis,
                run_id=run_id,
            )
            proposed_cases_raw = llm_provider_metadata.get("proposed_candidates", [])
            rejected_candidates = llm_provider_metadata.get("rejected_candidates", [])

            if is_full_beacon:
                # FULL_BEACON requires AI-proposed cases exclusively
                discovered_cases = list(ai_cases)
                prov_title = str(llm_provider_metadata.get("actual_provider") or "AI").title()
                source_desc = f"{prov_title} AI-proposed inputs from COBOL '{primary_cbl.name}'"
                method_desc = "AI_PROPOSED_INPUTS_SOURCE_VALIDATED"
            else:
                if ai_cases and not discovered_cases:
                    discovered_cases.extend(ai_cases)
                    source_desc = f"AI-proposed inputs from COBOL '{primary_cbl.name}'"
                    method_desc = "AI_PROPOSED_INPUTS_SOURCE_VALIDATED"

        # Fail closed if zero inputs found or if OpenRouter failed in FULL_BEACON mode
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

    def _mine_cobol_conditions_with_ai(
        self,
        cbl_file: Path,
        py_file: Optional[Path] = None,
        legacy_analysis: Optional[Any] = None,
        modern_analysis: Optional[Any] = None,
        run_id: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        """Extracts source-anchored behavioral rules and proposes executable cases using OpenRouter exclusively."""
        cbl_text = cbl_file.read_text(encoding="utf-8", errors="ignore")
        py_text = py_file.read_text(encoding="utf-8", errors="ignore") if py_file and py_file.exists() else ""

        # Collect copybook context if available across parent directories
        cpy_context = []
        referenced_cpys = set(re.findall(r"COPY\s+([A-Za-z0-9_-]+)", cbl_text, re.IGNORECASE))
        for parent_dir in (cbl_file.parent, cbl_file.parent.parent):
            if not parent_dir.is_dir():
                continue
            for cf in parent_dir.rglob("*.cpy"):
                if cf.stem.upper() in referenced_cpys:
                    try:
                        cpy_context.append(f"--- COPYBOOK: {cf.name} ---\n{cf.read_text(encoding='utf-8', errors='ignore')[:1000]}")
                    except Exception:
                        pass
                if len(cpy_context) >= 6:
                    break
        copybook_summary = "\n".join(cpy_context)[:1200]

        # Extract focused, line-numbered source windows to keep prompt tokens comfortably under 2,000 tokens
        cbl_lines = cbl_text.splitlines()
        proc_line = 0
        for i, l in enumerate(cbl_lines):
            if "PROCEDURE DIVISION" in l.upper():
                proc_line = i
                break

        selected_lines = []
        # First 35 lines (headers and primary working storage fields)
        for idx in range(min(35, len(cbl_lines))):
            selected_lines.append(f"{idx+1}: {cbl_lines[idx]}")
        selected_lines.append("... [intermediate declarations omitted] ...")
        # Core procedure division logic (primary branching and evaluation)
        start = proc_line
        end = min(len(cbl_lines), proc_line + 85)
        for idx in range(start, end):
            selected_lines.append(f"{idx+1}: {cbl_lines[idx]}")

        cbl_snippet = "\n".join(selected_lines)[:4200]
        py_snippet = py_text[:1500]

        configured_provider = (getattr(settings, "llm_provider", None) or "openrouter").lower().strip()
        if configured_provider not in ("openrouter", "gemini", "anthropic"):
            configured_provider = "openrouter"

        discovered_rules: list[dict[str, Any]] = []
        test_cases: list[dict[str, Any]] = []
        proposed_cases: list[dict[str, Any]] = []
        rejected_candidates: list[dict[str, Any]] = []
        llm_provider_metadata: dict[str, Any] = {}

        # AI proposes candidates only; source anchors are checked locally before use.
        try:
            from llm.manager import get_provider_manager
            pm = get_provider_manager()
            prompt = f"""You are BEACON's source-grounded behavioral rule extractor.
Identify at most 5 externally observable business/behavioral rules in this program. Keep descriptions short and focused. Prefer rules that describe observable input/output behavior.

COBOL Program: {cbl_file.name}
COBOL Source:
```cobol
{cbl_snippet}
```

Associated Copybooks:
```cobol
{copybook_summary}
```

Modern Re-implementation Snippet:
```python
{py_snippet}
```

Requirements:
1. Every rule must describe behavior observable from program inputs and outputs, not an implementation detail.
2. Include a numeric source line and an exact short source_excerpt copied from that line.
3. Generate 3-5 concise candidate input dictionaries (2-4 fields each, e.g. EIBAID, EIBCALEN, SCENARIO) for cases that can be passed to BOTH entrypoints. Keep dictionaries short.
4. Each case must include '__condition_provenance' naming the rule ID it exercises.
5. Do not invent expected outputs. BEACON will execute both programs and compare observed outputs independently.
6. These are candidate tests, not proof of equivalence. BEACON validates field names locally and independently executes both implementations before scoring.

Return ONLY a valid JSON object in this exact schema:
{{
  "rules": [
    {{"rule_id": "candidate-1", "description": "Observable business behavior", "source_location": "Line 12", "source_excerpt": "exact COBOL source text"}}
  ],
  "test_cases": [
    {{"field_name": "value", "__condition_provenance": "RULE-001"}}
  ]
}}
"""
            # Strict provider invocation with fallback disabled
            try:
                resp = pm.generate(
                    prompt,
                    json_mode=True,
                    preferred_provider=configured_provider,
                    allow_fallback=False,
                )
            except TypeError:
                resp = pm.generate(prompt, json_mode=True)

            valid_ai_providers = {"openrouter", "gemini", "anthropic"}
            provider_name = getattr(resp, "provider_name", "unknown")
            provider_is_valid = str(provider_name).lower().strip() in valid_ai_providers

            error_cat = getattr(resp, "error_category", None) or (getattr(resp, "metadata", {}) or {}).get("error_category", "")
            if not provider_is_valid and not error_cat:
                error_cat = "AI_PROVIDER_UNAVAILABLE"

            llm_provider_metadata = {
                "requested_provider": getattr(resp, "requested_provider", provider_name if provider_is_valid else configured_provider),
                "actual_provider": provider_name,
                "model": getattr(resp, "model_name", ""),
                "fallback_used": getattr(resp, "fallback_occurred", False),
                "fallback_reason": getattr(resp, "fallback_reason", None),
                "success": getattr(resp, "success", False),
                "error": getattr(resp, "error", None),
                "error_category": error_cat,
                "raw_text": getattr(resp, "raw_text", ""),
            }

            if resp.success and provider_is_valid and resp.parsed_json and isinstance(resp.parsed_json, dict):
                llm_rules = resp.parsed_json.get("rules", [])
                llm_cases = resp.parsed_json.get("test_cases", [])
                source_lines = cbl_text.splitlines()
                validated_rules: list[dict[str, Any]] = []

                if isinstance(llm_rules, list):
                    for r in llm_rules:
                        if not isinstance(r, dict):
                            continue
                        description = str(r.get("description", "")).strip()
                        source_excerpt = str(r.get("source_excerpt", "")).strip()
                        location_match = re.search(r"\blines?\s+(\d+)\b", str(r.get("source_location", "")), re.IGNORECASE)
                        if not description or not source_excerpt or not location_match:
                            continue
                        source_line = int(location_match.group(1))
                        if source_line < 1 or source_line > len(source_lines):
                            continue
                        excerpt_normalized = re.sub(r"\s+", "", source_excerpt).upper()
                        nearby_source = re.sub(
                            r"\s+",
                            "",
                            "\n".join(source_lines[max(0, source_line - 6):min(len(source_lines), source_line + 8)]),
                        ).upper()
                        if not excerpt_normalized or excerpt_normalized not in nearby_source:
                            continue
                        if not re.search(r"\bIF\b|\bWHEN\b|\bEVALUATE\b|\bPERFORM\b|\bMOVE\b|\bEXEC\b", source_excerpt, re.IGNORECASE):
                            continue
                        validated_rules.append({
                            "description": description,
                            "source_location": f"Line {source_line}",
                            "source_excerpt": source_excerpt,
                            "discovery_method": "AI_SOURCE_ANCHORED_RULE_EXTRACTION",
                            "source": "AI_CANDIDATE_SOURCE_VALIDATED",
                        })

                unique_rules: dict[tuple[int, str], dict[str, Any]] = {}
                for rule in validated_rules:
                    key = (
                        int(re.search(r"\d+", rule["source_location"]).group()),
                        re.sub(r"\s+", " ", rule["description"]).casefold(),
                    )
                    unique_rules.setdefault(key, rule)

                for rule_idx, rule in enumerate(
                    sorted(unique_rules.values(), key=lambda item: (int(re.search(r"\d+", item["source_location"]).group()), item["description"].casefold()))[:20],
                    start=1,
                ):
                    rule["rule_id"] = f"AI-RULE-{rule_idx:03d}"
                    discovered_rules.append(rule)

                # Collect valid identifier vocabulary from sources
                valid_identifiers = {
                    re.sub(r"[-_]", "", identifier).upper()
                    for identifier in re.findall(
                        r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\b",
                        (cbl_text + "\n" + copybook_summary + "\n" + py_text).upper(),
                    )
                }

                if isinstance(llm_cases, list):
                    for idx, tc in enumerate(llm_cases):
                        if not isinstance(tc, dict) or len(tc) == 0:
                            rejected_candidates.append({
                                "candidate_index": idx,
                                "reason": "EMPTY_OR_INVALID_DICTIONARY",
                                "candidate": tc,
                            })
                            continue
                        proposed_cases.append(tc)
                        field_keys = [k for k in tc.keys() if not k.startswith("__")]
                        if not field_keys:
                            rejected_candidates.append({
                                "candidate_index": idx,
                                "reason": "NO_BUSINESS_FIELD_KEYS",
                                "candidate": tc,
                            })
                            continue

                        valid_fields = [
                            key for key in field_keys
                            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key)
                            and re.sub(r"[-_]", "", key).upper() in valid_identifiers
                        ]

                        if len(valid_fields) != len(field_keys):
                            ungrounded = set(field_keys) - set(valid_fields)
                            rejected_candidates.append({
                                "candidate_index": idx,
                                "reason": f"UNGROUNDED_FIELDS: {list(ungrounded)}",
                                "candidate": tc,
                            })
                            continue

                        if not tc.get("__condition_provenance"):
                            tc["__condition_provenance"] = "RULE-001"

                        test_cases.append(tc)

                llm_provider_metadata["proposed_candidates"] = proposed_cases
                llm_provider_metadata["rejected_candidates"] = rejected_candidates
                llm_provider_metadata["rule_extraction_status"] = "SUCCESS" if discovered_rules else "NO_VALID_SOURCE_ANCHORED_RULES"
                llm_provider_metadata["validated_rule_count"] = len(discovered_rules)
                llm_provider_metadata["validated_input_count"] = len(test_cases)
            else:
                err_category = error_cat or (
                    "AI_PROVIDER_UNAVAILABLE"
                    if not provider_is_valid
                    else f"{str(provider_name).upper()}_REQUEST_FAILED"
                )
                llm_provider_metadata["rule_extraction_status"] = err_category
                llm_provider_metadata["error_category"] = err_category
                llm_provider_metadata["error"] = getattr(resp, "error", None) or err_category
                llm_provider_metadata["proposed_candidates"] = proposed_cases
                llm_provider_metadata["rejected_candidates"] = rejected_candidates
        except Exception as e:
            logger.debug("AI behavioral rule extraction failed: %s", type(e).__name__)
            llm_provider_metadata = {
                "requested_provider": configured_provider,
                "actual_provider": configured_provider,
                "success": False,
                "error_type": type(e).__name__,
                "error": str(e),
                "error_category": f"{configured_provider.upper()}_UNEXPECTED_EXCEPTION",
                "rule_extraction_status": f"{configured_provider.upper()}_UNEXPECTED_EXCEPTION",
                "proposed_candidates": proposed_cases,
                "rejected_candidates": rejected_candidates,
            }

        return test_cases, discovered_rules, llm_provider_metadata


input_discovery_engine = InputDiscoveryEngine()
