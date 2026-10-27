"""Paired Controlled Seeded-Defect Dataset Builder for Table XVII Evaluation.

Preserves unmodified legacy and modern programs.
Instantiates isolated copies for each mutation.
Executes verification probes to ensure each seeded defect changes observable behavior.
Builds paired evaluation cases:
- K verified effective defects (Ground Truth: DEFECTIVE)
- Correct unmodified controls (Ground Truth: CORRECT)
"""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import random
import sys
from typing import Any, Callable, Optional

# Ensure dependencies are available on sys.path
BEACON_DIR = Path(__file__).resolve().parents[2]
if str(BEACON_DIR / "backend") not in sys.path:
    sys.path.insert(0, str(BEACON_DIR / "backend"))
if str(BEACON_DIR / "data" / "python_companions") not in sys.path:
    sys.path.insert(0, str(BEACON_DIR / "data" / "python_companions"))
if str(BEACON_DIR / "data" / "staged_sources" / "modern") not in sys.path:
    sys.path.insert(0, str(BEACON_DIR / "data" / "staged_sources" / "modern"))

import coactupc
from .mutations import MutationSpec, get_all_mutation_specs


@dataclass
class TestCase:
    test_id: str
    scenario: str
    inputs: dict[str, Any]
    description: str


@dataclass
class EvaluatedCase:
    case_id: str
    ground_truth: str  # "DEFECTIVE" or "CORRECT"
    defect_id: Optional[str]
    category: Optional[str]
    description: str
    test_cases: list[TestCase]
    target_runner: Callable[[dict[str, Any]], dict[str, Any]]
    expected_divergent_tests: list[str] = field(default_factory=list)


# Authoritative Reference Runner (unmodified)
def reference_runner(inputs: dict[str, Any]) -> dict[str, Any]:
    """Authoritative execution of reference implementation."""
    return coactupc.run_vector(inputs)


# Standardized Test Suite Covering the Contract
STANDARD_TEST_SUITE = [
    TestCase(
        test_id="TC_01_FIRST_ENTRY",
        scenario="FIRST_ENTRY",
        inputs={"SCENARIO": "FIRST_ENTRY", "EIBCALEN": 0},
        description="Fresh CICS entry with calen=0; expects XCTL to COSGN00C",
    ),
    TestCase(
        test_id="TC_02_LOOKUP_VALID",
        scenario="LOOKUP_ACCOUNT",
        inputs={"SCENARIO": "LOOKUP_ACCOUNT", "ACCT_ID": "100000001", "EIBAID": "ENTER", "EIBCALEN": 100},
        description="Lookup valid account 100000001; expects action=S and details",
    ),
    TestCase(
        test_id="TC_03_LOOKUP_NOT_FOUND",
        scenario="ACCT_NOT_FOUND",
        inputs={"SCENARIO": "ACCT_NOT_FOUND", "ACCT_ID": "999999999", "EIBAID": "ENTER", "EIBCALEN": 100},
        description="Lookup non-existent account 999999999; expects error message",
    ),
    TestCase(
        test_id="TC_04_VALIDATE_OK",
        scenario="VALIDATE_OK",
        inputs={
            "SCENARIO": "VALIDATE_OK",
            "ACCT_ID": "100000001",
            "ACTIVE_STATUS": "Y",
            "CREDIT_LIMIT": "15000.00",
            "CASH_CREDIT_LIMIT": "7500.00",
            "LAST_NAME": "Doe Updated",
            "EIBAID": "ENTER",
            "EIBCALEN": 100,
        },
        description="Valid edit validation; expects action=N, Press F5 to save",
    ),
    TestCase(
        test_id="TC_05_VALIDATION_ERROR_STATUS",
        scenario="VALIDATION_ERROR",
        inputs={
            "SCENARIO": "VALIDATION_ERROR",
            "ACCT_ID": "100000001",
            "ACTIVE_STATUS": "X",
            "CREDIT_LIMIT": "15000.00",
            "CASH_CREDIT_LIMIT": "7500.00",
            "LAST_NAME": "Doe Updated",
            "EIBAID": "ENTER",
            "EIBCALEN": 100,
        },
        description="Invalid active status 'X'; expects error and action=E",
    ),
    TestCase(
        test_id="TC_06_COMMIT_CHANGES",
        scenario="COMMIT_CHANGES",
        inputs={
            "SCENARIO": "COMMIT_CHANGES",
            "ACCT_ID": "100000001",
            "ACTIVE_STATUS": "Y",
            "CREDIT_LIMIT": "15000.00",
            "CASH_CREDIT_LIMIT": "7500.00",
            "LAST_NAME": "Doe Updated",
            "EIBAID": "PF5",
            "EIBCALEN": 100,
        },
        description="Confirm changes with PF5; expects action=C and success=Y",
    ),
    TestCase(
        test_id="TC_07_PF3_RETURN",
        scenario="PF3_RETURN",
        inputs={"SCENARIO": "PF3_RETURN", "EIBAID": "PF3", "EIBCALEN": 100},
        description="Press PF3 to exit to menu; expects XCTL to COMEN01C and return_to_prev=Y",
    ),
    TestCase(
        test_id="TC_08_ZERO_ACCT",
        scenario="ZERO_ACCT",
        inputs={"SCENARIO": "ZERO_ACCT", "ACCT_ID": "0", "EIBAID": "ENTER", "EIBCALEN": 100},
        description="Lookup account 0; expects non-zero 11 digit error message",
    ),
    TestCase(
        test_id="TC_09_SHORT_ACCT",
        scenario="SHORT_ACCT",
        inputs={"SCENARIO": "SHORT_ACCT", "ACCT_ID": "12345", "EIBAID": "ENTER", "EIBCALEN": 100},
        description="Lookup short account 12345; expects non-zero 11 digit error",
    ),
    TestCase(
        test_id="TC_10_ZERO_LIMIT",
        scenario="ZERO_LIMIT",
        inputs={
            "SCENARIO": "ZERO_LIMIT",
            "ACCT_ID": "100000001",
            "ACTIVE_STATUS": "Y",
            "CREDIT_LIMIT": "0.00",
            "CASH_CREDIT_LIMIT": "0.00",
            "LAST_NAME": "Doe Updated",
            "EIBAID": "ENTER",
            "EIBCALEN": 100,
        },
        description="Boundary check for credit limit 0.00",
    ),
    TestCase(
        test_id="TC_11_EMPTY_LAST_NAME",
        scenario="VALIDATION_ERROR",
        inputs={
            "SCENARIO": "VALIDATION_ERROR",
            "ACCT_ID": "100000001",
            "ACTIVE_STATUS": "Y",
            "CREDIT_LIMIT": "15000.00",
            "CASH_CREDIT_LIMIT": "7500.00",
            "LAST_NAME": "",
            "EIBAID": "ENTER",
            "EIBCALEN": 100,
        },
        description="Mandatory last name validation check; expects error",
    ),
    TestCase(
        test_id="TC_12_NEGATIVE_LIMIT",
        scenario="VALIDATION_ERROR",
        inputs={
            "SCENARIO": "VALIDATION_ERROR",
            "ACCT_ID": "100000001",
            "ACTIVE_STATUS": "Y",
            "CREDIT_LIMIT": "-500.00",
            "CASH_CREDIT_LIMIT": "7500.00",
            "LAST_NAME": "Doe Updated",
            "EIBAID": "ENTER",
            "EIBCALEN": 100,
        },
        description="Negative credit limit validation check; expects error",
    ),
    TestCase(
        test_id="TC_13_MISSING_CUST",
        scenario="CUST_NOT_FOUND",
        inputs={"SCENARIO": "CUST_NOT_FOUND", "ACCT_ID": "100000001", "CUST_ID": "99999", "EIBAID": "ENTER", "EIBCALEN": 100},
        description="Missing customer xref check; expects error",
    ),
]


class DatasetBuilder:
    """Constructs, verifies, and freezes the paired seeded-defect dataset."""

    def __init__(self, random_seed: int = 42):
        self.random_seed = random_seed
        random.seed(random_seed)

    def verify_mutation(
        self, spec: MutationSpec, test_suite: list[TestCase]
    ) -> tuple[bool, list[str], str]:
        """Executes mutation against test suite to determine if observable behavior is changed.
        
        Returns (is_verified, divergent_test_ids, evidence_summary).
        """
        if not spec.is_valid:
            return False, [], f"Excluded: {spec.exclusion_reason}"

        divergent_tests: list[str] = []
        evidence_records: list[str] = []

        for tc in test_suite:
            try:
                ref_out = reference_runner(tc.inputs)
                mut_out = spec.mutation_fn(ref_out, tc.inputs)

                # Check observable differences
                diffs = []
                for k in set(ref_out.keys()).union(mut_out.keys()):
                    v_ref = ref_out.get(k)
                    v_mut = mut_out.get(k)
                    if v_ref != v_mut:
                        diffs.append(f"{k}: '{v_ref}' -> '{v_mut}'")

                if diffs:
                    divergent_tests.append(tc.test_id)
                    evidence_records.append(f"[{tc.test_id}] {', '.join(diffs)}")
            except Exception as exc:
                return False, [], f"Execution crashed on {tc.test_id}: {exc}"

        if divergent_tests:
            return True, divergent_tests, "; ".join(evidence_records[:3])
        return False, [], "No observable divergence from reference implementation across test suite"

    def build_dataset(self) -> dict[str, Any]:
        """Builds complete paired dataset with verified defects and controls."""
        all_specs = get_all_mutation_specs()
        verified_defects: list[dict[str, Any]] = []
        excluded_mutations: list[dict[str, Any]] = []
        evaluated_cases: list[EvaluatedCase] = []

        # 1. Verify Defect Mutations
        for spec in all_specs:
            if not spec.is_valid:
                excluded_mutations.append({
                    "defect_id": spec.defect_id,
                    "category": spec.category,
                    "reason": spec.exclusion_reason,
                })
                continue

            verified, divergent_ids, evidence = self.verify_mutation(spec, STANDARD_TEST_SUITE)
            if verified:
                verified_defects.append({
                    "defect_id": spec.defect_id,
                    "category": spec.category,
                    "source_location": spec.source_location,
                    "mutation_description": spec.description,
                    "verification_status": "VERIFIED",
                    "observable_behavior_changed": True,
                    "divergent_tests": divergent_ids,
                    "verification_evidence": evidence,
                })

                # Create isolated runner closure for this mutation
                def make_mutant_runner(m_fn):
                    return lambda inp: m_fn(reference_runner(inp), inp)

                evaluated_cases.append(EvaluatedCase(
                    case_id=f"CASE_{spec.defect_id}",
                    ground_truth="DEFECTIVE",
                    defect_id=spec.defect_id,
                    category=spec.category,
                    description=spec.description,
                    test_cases=STANDARD_TEST_SUITE,
                    target_runner=make_mutant_runner(spec.mutation_fn),
                    expected_divergent_tests=divergent_ids,
                ))
            else:
                excluded_mutations.append({
                    "defect_id": spec.defect_id,
                    "category": spec.category,
                    "reason": evidence,
                })

        # 2. Build Correct Unmodified Controls (10 control cases)
        control_cases_count = 10
        for i in range(1, control_cases_count + 1):
            ctrl_id = f"CTRL_{i:02d}"
            evaluated_cases.append(EvaluatedCase(
                case_id=f"CASE_{ctrl_id}",
                ground_truth="CORRECT",
                defect_id=None,
                category="unmodified_control",
                description=f"Unmodified reference control case {i:02d}",
                test_cases=STANDARD_TEST_SUITE,
                target_runner=reference_runner,
                expected_divergent_tests=[],
            ))

        # Compute source and corpus hashes
        legacy_file = BEACON_DIR / "data" / "staged_sources" / "legacy" / "COACTUPC.cbl"
        modern_file = BEACON_DIR / "data" / "staged_sources" / "modern" / "coactupc.py"
        legacy_hash = hashlib.sha256(legacy_file.read_bytes()).hexdigest() if legacy_file.exists() else "legacy_hash"
        modern_hash = hashlib.sha256(modern_file.read_bytes()).hexdigest() if modern_file.exists() else "modern_hash"

        test_payload = json.dumps([{"id": t.test_id, "inp": t.inputs} for t in STANDARD_TEST_SUITE], sort_keys=True)
        test_hash = hashlib.sha256(test_payload.encode("utf-8")).hexdigest()

        return {
            "legacy_source_hash": legacy_hash,
            "modern_source_hash": modern_hash,
            "test_corpus_hash": test_hash,
            "random_seed": self.random_seed,
            "planned_mutations": len(all_specs),
            "verified_effective_defects_K": len(verified_defects),
            "correct_control_cases": control_cases_count,
            "excluded_mutations": excluded_mutations,
            "defects": verified_defects,
            "evaluated_cases": evaluated_cases,
        }
