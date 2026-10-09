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

        ai_mined_rules: list[dict[str, Any]] = []
        llm_provider_metadata: dict[str, Any] = {}

        # Extract source-specific rules even when repository fixtures already supply inputs.
        cobol_candidates: list[Path] = []
        py_candidates: list[Path] = []
        for repo_p_str in [legacy_analysis.provenance.local_path, modern_analysis.provenance.local_path]:
            if not repo_p_str:
                continue
            repo_p = Path(repo_p_str)
            if repo_p.is_file():
                if repo_p.suffix.lower() in (".cbl", ".cob", ".cpy"):
                    cobol_candidates.append(repo_p)
                elif repo_p.suffix.lower() == ".py":
                    py_candidates.append(repo_p)
            else:
                for ext in ("*.cbl", "*.cob", "*.cpy", "*.CBL", "*.COB"):
                    cobol_candidates.extend(list(repo_p.rglob(ext)))
                py_candidates.extend(list(repo_p.rglob("*.py")))

        if cobol_candidates:
            primary_cbl = sorted(cobol_candidates, key=lambda path: str(path).lower())[0]
            primary_py = sorted(py_candidates, key=lambda path: str(path).lower())[0] if py_candidates else None
            ai_cases, ai_mined_rules, llm_provider_metadata = self._mine_cobol_conditions_with_ai(
                primary_cbl,
                primary_py,
            )
            if ai_cases and not discovered_cases:
                discovered_cases.extend(ai_cases)
                source_desc = f"AI-proposed inputs from COBOL '{primary_cbl.name}'"
                method_desc = "AI_PROPOSED_INPUTS_SOURCE_VALIDATED"

        # 3. Fail closed if zero legitimate inputs found — NEVER manufacture synthetic data!
        if not discovered_cases:
            return InputDiscoveryResult(
                status=InputDiscoveryStatus.INSUFFICIENT_COVERAGE,
                inputs_count=0,
                test_inputs=[],
                discovery_source="",
                discovery_method="FAILED",
                provenance={
                    "llm_provider": llm_provider_metadata,
                    "ai_mined_rules": ai_mined_rules,
                    "ai_mined_rule_count": len(ai_mined_rules),
                },
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
        seen_input_signatures: set[str] = set()
        for c_dict in selected_cases:
            input_values = {key: value for key, value in c_dict.items() if not key.startswith("__")}
            canonical_json = json.dumps(input_values, sort_keys=True, separators=(",", ":"), default=str)
            if canonical_json in seen_input_signatures:
                continue
            seen_input_signatures.add(canonical_json)
            inp_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
            inp_id = f"INP-{len(test_inputs)+1:04d}-{inp_hash[:8]}"
            test_inputs.append(
                CertificationTestInput(
                    input_id=inp_id,
                    values=input_values,
                    metadata={
                        "source": source_desc,
                        "index": len(test_inputs) + 1,
                        "condition_provenance": c_dict.get("__condition_provenance"),
                    },
                    provenance={
                        "discovery_method": method_desc,
                        "source": source_desc,
                        "input_hash": inp_hash,
                    },
                )
            )
        if not test_inputs:
            return InputDiscoveryResult(
                status=InputDiscoveryStatus.INSUFFICIENT_COVERAGE,
                inputs_count=0,
                test_inputs=[],
                discovery_source=source_desc,
                discovery_method="VALIDATION_FAILED",
                provenance={
                    "llm_provider": llm_provider_metadata,
                    "ai_mined_rules": ai_mined_rules,
                    "ai_mined_rule_count": len(ai_mined_rules),
                },
                diagnostic_message="Input discovery failed: all discovered cases were empty or duplicates.",
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
                "ai_mined_rules": ai_mined_rules,
                "ai_mined_rule_count": len(ai_mined_rules),
                "rule_extraction_status": llm_provider_metadata.get("rule_extraction_status", "NOT_ATTEMPTED"),
                "llm_provider": llm_provider_metadata,
            },
            diagnostic_message=f"Discovered {len(test_inputs)} authoritative test cases via {method_desc}.",
        )

    def _mine_cobol_conditions_with_ai(
        self,
        cbl_file: Path,
        py_file: Optional[Path] = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        """Extracts source-anchored behavioral rules and proposes executable cases using an LLM."""
        cbl_text = cbl_file.read_text(encoding="utf-8", errors="ignore")
        py_text = py_file.read_text(encoding="utf-8", errors="ignore") if py_file and py_file.exists() else ""

        # Collect copybook context if available across parent directories
        cpy_context = []
        referenced_cpys = set(re.findall(r"COPY\s+([A-Za-z0-9_-]+)", cbl_text, re.IGNORECASE))
        for parent_dir in (cbl_file.parent, cbl_file.parent.parent):
            if not parent_dir.is_dir():
                continue
            for cf in parent_dir.rglob("*.cpy"):
                if cf.stem.upper() in referenced_cpys or len(cpy_context) < 15:
                    try:
                        cpy_context.append(f"--- COPYBOOK: {cf.name} ---\n{cf.read_text(encoding='utf-8', errors='ignore')[:4000]}")
                    except Exception:
                        pass
        copybook_summary = "\n".join(cpy_context)[:40000]

        discovered_rules: list[dict[str, Any]] = []
        test_cases: list[dict[str, Any]] = []
        llm_provider_metadata: dict[str, Any] = {}

        # AI proposes candidates only; source anchors are checked locally before use.
        try:
            from llm.manager import get_provider_manager
            pm = get_provider_manager()
            prompt = f"""You are BEACON's source-grounded behavioral rule extractor.
Identify at most 20 externally observable business/behavioral rules in this program. Do not report every IF, EVALUATE, loop, flag, or control-flow condition as a separate rule. Prefer rules that describe observable input/output behavior.

COBOL Program: {cbl_file.name}
COBOL Source:
```cobol
{cbl_text[:120000]}
```

Associated Copybooks:
```cobol
{copybook_summary}
```

Modern Re-implementation Snippet:
```python
{py_text[:60000]}
```

Requirements:
1. Every rule must describe behavior observable from program inputs and outputs, not an implementation detail.
2. Include a numeric source line and an exact short source_excerpt copied from that line.
3. Generate a small set of concrete test input dictionaries using only declared input fields in the COBOL source or supplied copybooks.
4. Each case must include '__condition_provenance' naming the rule ID it exercises.
5. Do not invent expected outputs. BEACON will execute both programs and compare observed outputs independently.

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
            resp = pm.generate(prompt, json_mode=True)
            llm_provider_metadata = {
                "requested_provider": resp.requested_provider,
                "actual_provider": resp.provider_name,
                "model": resp.model_name,
                "fallback_used": resp.fallback_occurred,
                "fallback_reason": resp.fallback_reason,
                "success": resp.success,
            }
            provider_is_ai = str(resp.provider_name).lower() not in {"offline", "deterministic", "unavailable"}
            if resp.success and provider_is_ai and resp.parsed_json and isinstance(resp.parsed_json, dict):
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
                        location_match = re.search(r"\bline\s+(\d+)\b", str(r.get("source_location", "")), re.IGNORECASE)
                        if not description or not source_excerpt or not location_match:
                            continue
                        source_line = int(location_match.group(1))
                        if source_line < 1 or source_line > len(source_lines):
                            continue
                        excerpt_normalized = re.sub(r"\s+", "", source_excerpt).upper()
                        nearby_source = re.sub(
                            r"\s+",
                            "",
                            "\n".join(source_lines[max(0, source_line - 2):min(len(source_lines), source_line + 1)]),
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

                if isinstance(llm_cases, list):
                    for tc in llm_cases:
                        if isinstance(tc, dict) and len(tc) > 0:
                            field_keys = [k for k in tc.keys() if not k.startswith("__")]
                            valid_fields = [
                                key for key in field_keys
                                if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key)
                                and re.sub(r"[-_]", "", key).upper()
                                in {
                                    re.sub(r"[-_]", "", identifier).upper()
                                    for identifier in re.findall(
                                        r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\b",
                                        (cbl_text + "\n" + copybook_summary).upper(),
                                    )
                                }
                            ]
                            if valid_fields and len(valid_fields) == len(field_keys) and tc.get("__condition_provenance"):
                                test_cases.append(tc)
                llm_provider_metadata["rule_extraction_status"] = "SUCCESS" if discovered_rules else "NO_VALID_SOURCE_ANCHORED_RULES"
                llm_provider_metadata["validated_rule_count"] = len(discovered_rules)
                llm_provider_metadata["validated_input_count"] = len(test_cases)
            else:
                llm_provider_metadata["rule_extraction_status"] = "AI_PROVIDER_UNAVAILABLE"
        except Exception as e:
            logger.debug("LLM behavioral rule extraction failed: %s", type(e).__name__)
            llm_provider_metadata = {
                "actual_provider": "unavailable",
                "success": False,
                "error_type": type(e).__name__,
                "rule_extraction_status": "AI_PROVIDER_ERROR",
            }

        # No static or synthetic fallback is labelled as AI output.
        return test_cases, discovered_rules, llm_provider_metadata


input_discovery_engine = InputDiscoveryEngine()
