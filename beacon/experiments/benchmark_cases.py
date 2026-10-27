"""BEACON Research Evaluation Benchmark: 76 Genuine Source-Level Candidate Implementations for CardDemo COACTUPC.

Every candidate case executes an independent, genuine source-level Python program in
experiments/mutants/:
- 60 Defective Mutants across 5 Stratified Categories:
  1. incorrect_calculation (DEF_CALC_01..12)
  2. boundary_condition (DEF_BOUND_01..12)
  3. altered_business_rule (DEF_RULE_01..12)
  4. missing_update (DEF_UPDATE_01..12)
  5. incorrect_transaction_handling (DEF_TX_01..12)
- 15 Semantics-Preserving Equivalent Controls (EQUIV_01..15)
- 1 Clean Candidate (CTRL_00)

No output-interception wrappers are used; each candidate compiles and executes through
its own process_account_update(...) function with verified source-level modifications.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys
from typing import Any, Callable, Optional

# Ensure dependencies on sys.path
BEACON_DIR = Path(__file__).resolve().parent.parent
COMPANIONS_DIR = BEACON_DIR / "data" / "python_companions"
MODERN_DIR = BEACON_DIR / "data" / "staged_sources" / "modern"
MUTANTS_DIR = BEACON_DIR / "experiments" / "mutants"

if str(COMPANIONS_DIR) not in sys.path:
    sys.path.insert(0, str(COMPANIONS_DIR))
if str(MODERN_DIR) not in sys.path:
    sys.path.insert(0, str(MODERN_DIR))

from carddemo_data import (
    CarddemoCommarea, ScreenHeader,
    AccountRecord, CustomerRecord, CardXrefRecord,
    DFHENTER, DFHPF3, DFHPF5, DFHPF12,
)
import coactupc
from coactupc import (
    AccountUpdateInput, process_account_update,
    AccountRepository, CustomerRepository, XrefRepository,
    _SEED_ACCOUNTS, _SEED_CUSTOMERS, _SEED_XREFS,
    WS_TRANID, WS_PGMNAME,
)


@dataclass
class BenchmarkCaseSpec:
    case_id: str
    category: str
    operator: str
    source_location: str
    description: str
    trigger_condition: str
    expected_observable_difference: str
    ground_truth: str  # "DEFECTIVE" or "EQUIVALENT"
    runner: Callable[[dict[str, Any]], dict[str, Any]]
    source_file: str = ""
    source_sha256: str = ""
    canonical_sha256: str = ""
    reviewer: str = "author_only"
    estimated_trigger_rate: float = 0.0
    difficulty: str = "easy"  # easy (>1%), medium (0.1%-1%), hard (<=0.1%)


# ─── Reference Runner ────────────────────────────────────────────────────────

def reference_runner(inputs: dict[str, Any]) -> dict[str, Any]:
    """Authoritative reference execution of CardDemo COACTUPC."""
    calen = int(inputs.get("EIBCALEN", 100))
    aid = str(inputs.get("EIBAID", "ENTER")).upper().strip()
    action = str(inputs.get("ACTION", "S")).strip()
    acct_id = str(inputs.get("ACCT_ID", "100000001")).strip()

    commarea = CarddemoCommarea(
        cdemo_from_tranid=inputs.get("FROM_TRANID", "CM00"),
        cdemo_from_program=inputs.get("FROM_PROGRAM", "COMEN01C"),
        cdemo_user_id="USER0001",
        cdemo_user_type="U",
        cdemo_pgm_context=1,
    )
    acct_repo = AccountRepository(dict(_SEED_ACCOUNTS))
    cust_repo = CustomerRepository(dict(_SEED_CUSTOMERS))
    xref_repo = XrefRepository(list(_SEED_XREFS))

    inp = AccountUpdateInput(
        acct_id=acct_id,
        active_status=str(inputs.get("ACTIVE_STATUS", "Y")).strip(),
        credit_limit=str(inputs.get("CREDIT_LIMIT", "10000.00")).strip(),
        cash_credit_limit=str(inputs.get("CASH_CREDIT_LIMIT", "5000.00")).strip(),
        curr_bal=str(inputs.get("CURR_BAL", "5000.00")).strip(),
        last_name=str(inputs.get("LAST_NAME", "Doe")).strip(),
        first_name=str(inputs.get("FIRST_NAME", "John")).strip(),
        fico_score=str(inputs.get("FICO_SCORE", "750")).strip(),
        addr_zip=str(inputs.get("ADDR_ZIP", "10001")).strip(),
    )

    old_acct = acct_repo.find(100000001)
    old_cust = cust_repo.find(1)

    res = process_account_update(
        eibcalen=calen,
        eibaid=aid,
        commarea=commarea,
        inp=inp,
        acct_repo=acct_repo,
        cust_repo=cust_repo,
        xref_repo=xref_repo,
        current_action=action,
        old_acct=old_acct,
        old_cust=old_cust,
    )

    return {
        "ACTION": res.action,
        "ERROR": "Y" if res.error else "N",
        "SUCCESS": "Y" if res.success else "N",
        "MESSAGE": res.message,
        "XCTL_PROGRAM": res.xctl_program or "",
        "RETURN_TO_PREV": "Y" if res.return_to_prev else "N",
        "ACCT_ID": str(res.acct_record.acct_id) if res.acct_record else "",
        "ACCT_STATUS": res.acct_record.acct_active_status if res.acct_record else "",
        "ACCT_BAL": str(res.acct_record.acct_curr_bal) if res.acct_record else "",
        "CREDIT_LIMIT": str(res.acct_record.acct_credit_limit) if res.acct_record and hasattr(res.acct_record, "acct_credit_limit") else "",
        "CASH_CREDIT_LIMIT": str(res.acct_record.acct_cash_credit_limit) if res.acct_record and hasattr(res.acct_record, "acct_cash_credit_limit") else "",
        "LAST_NAME": res.cust_record.cust_last_name if res.cust_record else "",
    }


# ─── Candidate Runner Factory ────────────────────────────────────────────────

_MUTANT_MODULE_CACHE: dict[str, Any] = {}

def make_candidate_runner(case_id: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Loads a genuine candidate mutant module and creates its execution runner."""
    if case_id in _MUTANT_MODULE_CACHE:
        mod = _MUTANT_MODULE_CACHE[case_id]
    else:
        mutant_file = MUTANTS_DIR / f"candidate_{case_id}.py"
        if not mutant_file.exists():
            raise FileNotFoundError(f"Mutant source file not found: {mutant_file}")
        
        module_name = f"mutant_{case_id}"
        spec = importlib.util.spec_from_file_location(module_name, mutant_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load spec for {mutant_file}")
        
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        _MUTANT_MODULE_CACHE[case_id] = mod

    process_fn = mod.process_account_update
    AccountUpdateInput = mod.AccountUpdateInput
    AccountRepository = mod.AccountRepository
    CustomerRepository = mod.CustomerRepository
    XrefRepository = mod.XrefRepository
    CarddemoCommarea = mod.CarddemoCommarea
    _SEED_ACCOUNTS = mod._SEED_ACCOUNTS
    _SEED_CUSTOMERS = mod._SEED_CUSTOMERS
    _SEED_XREFS = mod._SEED_XREFS

    def candidate_runner(inputs: dict[str, Any]) -> dict[str, Any]:
        calen = int(inputs.get("EIBCALEN", 100))
        aid = str(inputs.get("EIBAID", "ENTER")).upper().strip()
        action = str(inputs.get("ACTION", "S")).strip()
        acct_id = str(inputs.get("ACCT_ID", "100000001")).strip()

        commarea = CarddemoCommarea(
            cdemo_from_tranid=inputs.get("FROM_TRANID", "CM00"),
            cdemo_from_program=inputs.get("FROM_PROGRAM", "COMEN01C"),
            cdemo_user_id="USER0001",
            cdemo_user_type="U",
            cdemo_pgm_context=1,
        )
        acct_repo = AccountRepository(dict(_SEED_ACCOUNTS))
        cust_repo = CustomerRepository(dict(_SEED_CUSTOMERS))
        xref_repo = XrefRepository(list(_SEED_XREFS))

        inp = AccountUpdateInput(
            acct_id=acct_id,
            active_status=str(inputs.get("ACTIVE_STATUS", "Y")).strip(),
            credit_limit=str(inputs.get("CREDIT_LIMIT", "10000.00")).strip(),
            cash_credit_limit=str(inputs.get("CASH_CREDIT_LIMIT", "5000.00")).strip(),
            curr_bal=str(inputs.get("CURR_BAL", "5000.00")).strip(),
            last_name=str(inputs.get("LAST_NAME", "Doe")).strip(),
            first_name=str(inputs.get("FIRST_NAME", "John")).strip(),
            fico_score=str(inputs.get("FICO_SCORE", "750")).strip(),
            addr_zip=str(inputs.get("ADDR_ZIP", "10001")).strip(),
        )

        old_acct = acct_repo.find(100000001)
        old_cust = cust_repo.find(1)

        res = process_fn(
            eibcalen=calen,
            eibaid=aid,
            commarea=commarea,
            inp=inp,
            acct_repo=acct_repo,
            cust_repo=cust_repo,
            xref_repo=xref_repo,
            current_action=action,
            old_acct=old_acct,
            old_cust=old_cust,
        )

        return {
            "ACTION": res.action,
            "ERROR": "Y" if res.error else "N",
            "SUCCESS": "Y" if res.success else "N",
            "MESSAGE": res.message,
            "XCTL_PROGRAM": res.xctl_program or "",
            "RETURN_TO_PREV": "Y" if res.return_to_prev else "N",
            "ACCT_ID": str(res.acct_record.acct_id) if res.acct_record else "",
            "ACCT_STATUS": res.acct_record.acct_active_status if res.acct_record else "",
            "ACCT_BAL": str(res.acct_record.acct_curr_bal) if res.acct_record else "",
            "CREDIT_LIMIT": str(res.acct_record.acct_credit_limit) if res.acct_record and hasattr(res.acct_record, "acct_credit_limit") else "",
            "CASH_CREDIT_LIMIT": str(res.acct_record.acct_cash_credit_limit) if res.acct_record and hasattr(res.acct_record, "acct_cash_credit_limit") else "",
            "LAST_NAME": res.cust_record.cust_last_name if res.cust_record else "",
        }

    return candidate_runner


# ─── Input Generation Contract ───────────────────────────────────────────────

def generate_random_valid_input(rng: random.Random) -> dict[str, Any]:
    """Generates an independent, syntactically and semantically valid transaction input."""
    state_choice = rng.random()
    calen = 0 if state_choice < 0.08 else (1 if rng.random() < 0.02 else 100)

    if state_choice < 0.08:
        # First entry
        return {"EIBCALEN": 0, "EIBAID": "ENTER", "ACTION": "", "ACCT_ID": "100000001"}
    elif state_choice < 0.16:
        # PF3 menu navigation
        from_prog = rng.choice(["COMEN01C", "COCRDLIC", "COSGN00C"])
        return {"EIBCALEN": calen, "EIBAID": "PF3", "ACTION": rng.choice(["", "S", "N"]), "FROM_PROGRAM": from_prog}
    elif state_choice < 0.24:
        # PF12 card list navigation
        return {"EIBCALEN": calen, "EIBAID": "PF12", "ACTION": "N", "ACCT_ID": "100000001"}
    elif state_choice < 0.40:
        # Initial account lookup
        acct_candidates = ["100000001", "100000002", "100000003", "999999999", "0", "12345", "ABC1234"]
        return {
            "EIBCALEN": calen,
            "EIBAID": "ENTER",
            "ACTION": "",
            "ACCT_ID": rng.choice(acct_candidates),
        }
    elif state_choice < 0.70:
        # Validation / Preview phase (ACTION = 'S')
        statuses = ["Y", "N", "Y", "N", "X", "P", ""]
        limits = ["5000.00", "10000.00", "15000.00", "20000.00", "25000.00", "50000.00", "99999.00", "99999.99", "0.00", "-50.00", "INVALID"]
        last_names = ["Doe", "Smith", "Johnson", "Williams", "Brown", "O'Connor", "A", "", "   "]
        cred = rng.choice(limits)
        try:
            val = float(cred)
            cash_cred = f"{val * 0.5:.2f}" if rng.random() > 0.15 else f"{val * 1.2:.2f}"
        except ValueError:
            cash_cred = "2500.00"

        aid = rng.choice(["ENTER", "ENTER", "ENTER", "ENTER", "ENTER", "PF3", "PF5", "PF12"])
        return {
            "EIBCALEN": calen,
            "EIBAID": aid,
            "ACTION": "S",
            "ACCT_ID": rng.choice(["100000001", "100000002", "100000003"]),
            "ACTIVE_STATUS": rng.choice(statuses),
            "CREDIT_LIMIT": cred,
            "CASH_CREDIT_LIMIT": cash_cred,
            "CURR_BAL": rng.choice(["2500.00", "5000.00", "0.00", "-100.00"]),
            "LAST_NAME": rng.choice(last_names),
            "FIRST_NAME": rng.choice(["John", "Jane", "Alice", "Bob", ""]),
            "FICO_SCORE": rng.choice(["750", "800", "650", "850", "300", "250", "900"]),
            "ADDR_ZIP": rng.choice(["10001", "90210", "12345", "9999", "123456"]),
        }
    else:
        # Commit phase (ACTION = 'N', PF5 confirmation)
        aid = rng.choice(["PF5", "PF5", "ENTER", "PF3", "PF12"])
        return {
            "EIBCALEN": calen,
            "EIBAID": aid,
            "ACTION": "N",
            "ACCT_ID": rng.choice(["100000001", "100000002", "100000003"]),
            "ACTIVE_STATUS": rng.choice(["Y", "N"]),
            "CREDIT_LIMIT": rng.choice(["12000.00", "15000.00", "20000.00", "25000.00"]),
            "CASH_CREDIT_LIMIT": "6000.00",
            "CURR_BAL": "5000.00",
            "LAST_NAME": rng.choice(["Doe Updated", "Smith", "Johnson"]),
            "FIRST_NAME": "John",
            "FICO_SCORE": "750",
            "ADDR_ZIP": "10001",
        }


def generate_canonical_input_suite(budget: int, seed: int) -> tuple[list[dict[str, Any]], str]:
    """Generates an immutable list of inputs and returns (inputs, canonical_sha256_digest)."""
    rng = random.Random(seed)
    suite = [generate_random_valid_input(rng) for _ in range(budget)]
    payload = json.dumps(suite, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return suite, digest


# ─── Load All Benchmark Cases ────────────────────────────────────────────────

def get_all_benchmark_cases() -> list[BenchmarkCaseSpec]:
    """Loads all 76 benchmark cases from the source mutant manifest."""
    manifest_path = BEACON_DIR / "results" / "source_mutants_manifest.json"
    if not manifest_path.exists():
        # Auto-generate if missing
        from experiments.build_source_mutants import generate_all_mutants
        generate_all_mutants()

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    cases: list[BenchmarkCaseSpec] = []
    for entry in manifest["cases"]:
        cid = entry["case_id"]
        runner = make_candidate_runner(cid)
        cases.append(BenchmarkCaseSpec(
            case_id=cid,
            category=entry["category"],
            operator=entry["operator"],
            source_location=f"{entry['source_file']}:{entry['changed_line']}",
            description=entry["description"],
            trigger_condition=entry["trigger_condition"],
            expected_observable_difference=entry["expected_observable_difference"],
            ground_truth=entry["ground_truth"],
            runner=runner,
            source_file=entry["source_file"],
            source_sha256=entry["mutated_source_hash"],
            canonical_sha256=entry["canonical_source_hash"],
        ))

    return cases
