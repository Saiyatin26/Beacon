"""BEACON Research Evaluation Benchmark: 76 Paired Evaluation Cases for AWS CardDemo COACTUPC.

Includes:
- 60 Defective Mutants across 5 Stratified Categories (12 per category):
  1. incorrect_calculation
  2. boundary_condition
  3. altered_business_rule
  4. missing_update
  5. incorrect_transaction_handling
- 15 Semantics-Preserving Equivalent Controls (refactorings/rewrites)
- 1 Clean Control Candidate (CTRL_00)

Every mutant provides:
- case_id, category, operator, source_location, description, trigger_condition
- expected_observable_difference, ground_truth ('DEFECTIVE' or 'EQUIVALENT')
- isolated runner callable(inputs: dict) -> dict
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import random
import sys
from typing import Any, Callable, Optional

# Ensure dependencies on sys.path
BEACON_DIR = Path(__file__).resolve().parent.parent
if str(BEACON_DIR / "data" / "python_companions") not in sys.path:
    sys.path.insert(0, str(BEACON_DIR / "data" / "python_companions"))
if str(BEACON_DIR / "data" / "staged_sources" / "modern") not in sys.path:
    sys.path.insert(0, str(BEACON_DIR / "data" / "staged_sources" / "modern"))

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


# ─── Mutants Builder (60 Defective + 15 Equivalent + 1 Clean) ───────────────

def get_all_benchmark_cases() -> list[BenchmarkCaseSpec]:
    """Assembles all 76 benchmark cases."""
    cases: list[BenchmarkCaseSpec] = []

    # ── Clean Control #0 ──
    cases.append(BenchmarkCaseSpec(
        case_id="CTRL_00",
        category="clean_control",
        operator="identity",
        source_location="coactupc.py:1-567",
        description="Clean, unmodified modern Python candidate implementation",
        trigger_condition="None (unmodified reference behavior)",
        expected_observable_difference="None (strictly certified)",
        ground_truth="EQUIVALENT",
        runner=reference_runner,
    ))

    # ─────────────────────────────────────────────────────────────────────────
    # Category 1: incorrect_calculation (12 cases)
    # ─────────────────────────────────────────────────────────────────────────

    def m_calc_01(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "S" and out["ACTION"] == "N":
            try:
                val = float(out["CREDIT_LIMIT"]) - 50.0
                out["CREDIT_LIMIT"] = f"{val:.2f}"
            except (ValueError, KeyError):
                pass
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_01", category="incorrect_calculation", operator="unauthorized_fee_deduction",
        source_location="coactupc.py:351", description="Deducts unauthorized $50 fee from validated credit limit",
        trigger_condition="ACTION == 'S' with valid edits",
        expected_observable_difference="CREDIT_LIMIT is $50 less than expected",
        ground_truth="DEFECTIVE", runner=m_calc_01,
    ))

    def m_calc_02(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "S" and out["ACTION"] == "N":
            out["CASH_CREDIT_LIMIT"] = out.get("CREDIT_LIMIT", "")
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_02", category="incorrect_calculation", operator="cash_credit_mirroring",
        source_location="coactupc.py:356", description="Sets cash credit limit equal to full credit limit instead of 50% cap",
        trigger_condition="ACTION == 'S' with valid edits",
        expected_observable_difference="CASH_CREDIT_LIMIT mirrors CREDIT_LIMIT",
        ground_truth="DEFECTIVE", runner=m_calc_02,
    ))

    def m_calc_03(inp):
        out = reference_runner(inp)
        if out["CREDIT_LIMIT"]:
            try:
                val = int(float(out["CREDIT_LIMIT"]))
                out["CREDIT_LIMIT"] = f"{val:.2f}"
            except ValueError:
                pass
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_03", category="incorrect_calculation", operator="decimal_truncation",
        source_location="coactupc.py:351", description="Truncates decimal cents from credit limit during assignment",
        trigger_condition="Any transaction outputting fractional credit limit cents",
        expected_observable_difference="CREDIT_LIMIT cents truncated to .00",
        ground_truth="DEFECTIVE", runner=m_calc_03,
    ))

    def m_calc_04(inp):
        out = reference_runner(inp)
        if out["ACCT_BAL"]:
            try:
                val = -float(out["ACCT_BAL"])
                out["ACCT_BAL"] = f"{val:.2f}"
            except ValueError:
                pass
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_04", category="incorrect_calculation", operator="balance_inversion",
        source_location="coactupc.py:361", description="Inverts current account balance sign (+ to -)",
        trigger_condition="Any transaction displaying account balance",
        expected_observable_difference="ACCT_BAL sign inverted",
        ground_truth="DEFECTIVE", runner=m_calc_04,
    ))

    def m_calc_05(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "S" and out["ACTION"] == "N":
            try:
                val = float(out["CASH_CREDIT_LIMIT"]) * 1.5
                out["CASH_CREDIT_LIMIT"] = f"{val:.2f}"
            except ValueError:
                pass
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_05", category="incorrect_calculation", operator="cash_credit_surcharge",
        source_location="coactupc.py:356", description="Applies 50% surcharge multiplier to cash credit limit",
        trigger_condition="ACTION == 'S' with valid edits",
        expected_observable_difference="CASH_CREDIT_LIMIT multiplied by 1.5",
        ground_truth="DEFECTIVE", runner=m_calc_05,
    ))

    def m_calc_06(inp):
        out = reference_runner(inp)
        if out["CREDIT_LIMIT"]:
            try:
                val = float(out["CREDIT_LIMIT"])
                rounded = (int(val) // 10) * 10
                out["CREDIT_LIMIT"] = f"{rounded:.2f}"
            except ValueError:
                pass
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_06", category="incorrect_calculation", operator="coarse_rounding",
        source_location="coactupc.py:351", description="Rounds credit limit down to nearest ten dollars",
        trigger_condition="Credit limit with non-zero units digit",
        expected_observable_difference="CREDIT_LIMIT rounded to nearest 10",
        ground_truth="DEFECTIVE", runner=m_calc_06,
    ))

    def m_calc_07(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "S" and out["ACTION"] == "N":
            try:
                val = float(out["CREDIT_LIMIT"]) * 1.05
                out["CREDIT_LIMIT"] = f"{val:.2f}"
            except ValueError:
                pass
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_07", category="incorrect_calculation", operator="rate_surcharge",
        source_location="coactupc.py:351", description="Multiplies updated credit limit by 1.05 rate surcharge",
        trigger_condition="ACTION == 'S' with valid edits",
        expected_observable_difference="CREDIT_LIMIT inflated by 5%",
        ground_truth="DEFECTIVE", runner=m_calc_07,
    ))

    def m_calc_08(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "S" and out["ACTION"] == "N":
            try:
                limit = float(out["CREDIT_LIMIT"])
                bal = float(out["ACCT_BAL"] or 0.0)
                out["CREDIT_LIMIT"] = f"{limit - bal:.2f}"
            except ValueError:
                pass
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_08", category="incorrect_calculation", operator="balance_offset",
        source_location="coactupc.py:351", description="Erroneously subtracts current balance from credit limit",
        trigger_condition="ACTION == 'S' with valid edits and non-zero balance",
        expected_observable_difference="CREDIT_LIMIT reduced by ACCT_BAL",
        ground_truth="DEFECTIVE", runner=m_calc_08,
    ))

    def m_calc_09(inp):
        out = reference_runner(inp)
        if inp.get("CASH_CREDIT_LIMIT") in ("0", "0.00"):
            out["CASH_CREDIT_LIMIT"] = "-1.00"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_09", category="incorrect_calculation", operator="zero_underflow",
        source_location="coactupc.py:356", description="Converts 0.00 cash credit limit into negative -1.00",
        trigger_condition="CASH_CREDIT_LIMIT == '0.00'",
        expected_observable_difference="CASH_CREDIT_LIMIT becomes -1.00",
        ground_truth="DEFECTIVE", runner=m_calc_09,
    ))

    def m_calc_10(inp):
        out = reference_runner(inp)
        if out["CASH_CREDIT_LIMIT"]:
            try:
                val = float(out["CASH_CREDIT_LIMIT"]) / 10.0
                out["CASH_CREDIT_LIMIT"] = f"{val:.2f}"
            except ValueError:
                pass
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_10", category="incorrect_calculation", operator="decimal_shift",
        source_location="coactupc.py:356", description="Divides cash credit limit by 10 (decimal point shift)",
        trigger_condition="Any transaction returning non-zero CASH_CREDIT_LIMIT",
        expected_observable_difference="CASH_CREDIT_LIMIT divided by 10",
        ground_truth="DEFECTIVE", runner=m_calc_10,
    ))

    def m_calc_11(inp):
        # HARD (trigger rate <= 0.1%): Triggered ONLY when credit limit is 99999.99 with status Y and last_name Doe on preview
        out = reference_runner(inp)
        cred = str(inp.get("CREDIT_LIMIT", "")).strip()
        status = str(inp.get("ACTIVE_STATUS", "")).strip().upper()
        last = str(inp.get("LAST_NAME", "")).strip()
        if (inp.get("ACTION") == "S" and cred == "99999.99" and
            status == "Y" and last == "Doe" and out["ACTION"] == "N"):
            out["CREDIT_LIMIT"] = "0.00"
            out["MESSAGE"] = "Precision overflow on limit"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_11", category="incorrect_calculation", operator="precision_overflow_rare",
        source_location="coactupc.py:351", description="Truncates limit to 0.00 only when credit limit ends in .99",
        trigger_condition="ACTION == 'S' and CREDIT_LIMIT ends in '.99'",
        expected_observable_difference="CREDIT_LIMIT becomes '0.00'",
        ground_truth="DEFECTIVE", runner=m_calc_11,
    ))

    def m_calc_12(inp):
        # HARD (trigger rate <= 0.1%): Triggered ONLY when CREDIT_LIMIT == '25000.00' and CASH_CREDIT_LIMIT == '12500.00'
        out = reference_runner(inp)
        if (str(inp.get("CREDIT_LIMIT", "")).strip() == "25000.00" and
            str(inp.get("CASH_CREDIT_LIMIT", "")).strip() == "12500.00" and
            inp.get("ACTION") == "S"):
            out["CREDIT_LIMIT"] = "24000.00"
            out["MESSAGE"] = "Maximum bracket audit penalty applied"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_CALC_12", category="incorrect_calculation", operator="bracket_penalty_rare",
        source_location="coactupc.py:351", description="Deducts $1,000 penalty only on exact 25000.00/12500.00 combination",
        trigger_condition="CREDIT_LIMIT == '25000.00' and CASH_CREDIT_LIMIT == '12500.00' and ACTION == 'S'",
        expected_observable_difference="CREDIT_LIMIT reduced to 24000.00",
        ground_truth="DEFECTIVE", runner=m_calc_12,
    ))

    # ─────────────────────────────────────────────────────────────────────────
    # Category 2: boundary_condition (12 cases)
    # ─────────────────────────────────────────────────────────────────────────

    def m_bound_01(inp):
        out = reference_runner(inp)
        if str(inp.get("CREDIT_LIMIT", "")).strip() in ("0.00", "0"):
            out["ACTION"] = "E"
            out["ERROR"] = "Y"
            out["MESSAGE"] = "Credit limit cannot be zero"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_01", category="boundary_condition", operator="reject_zero_limit",
        source_location="coactupc.py:328", description="Rejects zero credit limit (requires strict positive value)",
        trigger_condition="CREDIT_LIMIT == '0.00'",
        expected_observable_difference="ACTION becomes 'E', ERROR becomes 'Y'",
        ground_truth="DEFECTIVE", runner=m_bound_01,
    ))

    def m_bound_02(inp):
        out = reference_runner(inp)
        cred = str(inp.get("CREDIT_LIMIT", "")).strip()
        try:
            if float(cred) >= 50000.00 and inp.get("ACTION") == "S":
                out["ACTION"] = "E"
                out["ERROR"] = "Y"
                out["MESSAGE"] = "Credit limit exceeds maximum ceiling"
        except ValueError:
            pass
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_02", category="boundary_condition", operator="premature_ceiling_clamp",
        source_location="coactupc.py:328", description="Rejects credit limits >= 50,000 prematurely",
        trigger_condition="CREDIT_LIMIT >= 50000.00 and ACTION == 'S'",
        expected_observable_difference="Rejects valid high limits >= 50000",
        ground_truth="DEFECTIVE", runner=m_bound_02,
    ))

    def m_bound_03(inp):
        out = reference_runner(inp)
        acct = str(inp.get("ACCT_ID", "")).strip()
        if len(acct) > 0 and len(acct) < 9 and inp.get("ACTION") == "":
            out["ERROR"] = "N"
            out["ACTION"] = "S"
            out["MESSAGE"] = "Short account padded and accepted"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_03", category="boundary_condition", operator="short_acct_permissive",
        source_location="coactupc.py:202", description="Permits short account IDs (<9 digits) without error flag",
        trigger_condition="ACCT_ID with length < 9 and ACTION == ''",
        expected_observable_difference="Suppresses error on short ACCT_ID",
        ground_truth="DEFECTIVE", runner=m_bound_03,
    ))

    def m_bound_04(inp):
        out = reference_runner(inp)
        cred = str(inp.get("CREDIT_LIMIT", "")).strip()
        if cred.startswith("-") and inp.get("ACTION") == "S":
            out["ACTION"] = "N"
            out["ERROR"] = "N"
            out["MESSAGE"] = "Changes validated.Press F5 to save"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_04", category="boundary_condition", operator="permit_negative_limit",
        source_location="coactupc.py:328", description="Permits negative credit limit values to pass validation",
        trigger_condition="CREDIT_LIMIT < 0 and ACTION == 'S'",
        expected_observable_difference="ACTION becomes 'N' instead of 'E'",
        ground_truth="DEFECTIVE", runner=m_bound_04,
    ))

    def m_bound_05(inp):
        out = reference_runner(inp)
        cred = str(inp.get("CREDIT_LIMIT", "")).strip()
        cash = str(inp.get("CASH_CREDIT_LIMIT", "")).strip()
        if cred == cash and cred != "" and inp.get("ACTION") == "S":
            out["ACTION"] = "E"
            out["ERROR"] = "Y"
            out["MESSAGE"] = "Cash limit cannot equal total credit limit"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_05", category="boundary_condition", operator="reject_equal_limits",
        source_location="coactupc.py:320", description="Strictly rejects cash credit limit equal to credit limit",
        trigger_condition="CASH_CREDIT_LIMIT == CREDIT_LIMIT and ACTION == 'S'",
        expected_observable_difference="ACTION becomes 'E'",
        ground_truth="DEFECTIVE", runner=m_bound_05,
    ))

    def m_bound_06(inp):
        out = reference_runner(inp)
        fico = str(inp.get("FICO_SCORE", "")).strip()
        try:
            if int(fico) < 300 and inp.get("ACTION") == "S":
                out["ACTION"] = "N"
                out["ERROR"] = "N"
                out["MESSAGE"] = "Changes validated.Press F5 to save"
        except ValueError:
            pass
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_06", category="boundary_condition", operator="permit_underflow_fico",
        source_location="coactupc.py:399", description="Permits FICO score below 300 minimum boundary",
        trigger_condition="FICO_SCORE < 300 and ACTION == 'S'",
        expected_observable_difference="FICO underflow accepted",
        ground_truth="DEFECTIVE", runner=m_bound_06,
    ))

    def m_bound_07(inp):
        out = reference_runner(inp)
        zip_c = str(inp.get("ADDR_ZIP", "")).strip()
        if len(zip_c) == 4 and inp.get("ACTION") == "S":
            out["ACTION"] = "N"
            out["ERROR"] = "N"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_07", category="boundary_condition", operator="permit_short_zip",
        source_location="coactupc.py:391", description="Accepts 4-digit zip codes without zero-padding",
        trigger_condition="len(ADDR_ZIP) == 4 and ACTION == 'S'",
        expected_observable_difference="Accepts invalid 4-digit zip code",
        ground_truth="DEFECTIVE", runner=m_bound_07,
    ))

    def m_bound_08(inp):
        out = reference_runner(inp)
        last = str(inp.get("LAST_NAME", "")).strip()
        if len(last) == 1 and inp.get("ACTION") == "S":
            out["ACTION"] = "E"
            out["ERROR"] = "Y"
            out["MESSAGE"] = "Last name must be at least 2 characters"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_08", category="boundary_condition", operator="reject_single_char_name",
        source_location="coactupc.py:334", description="Rejects valid 1-letter last names",
        trigger_condition="len(LAST_NAME) == 1 and ACTION == 'S'",
        expected_observable_difference="ACTION becomes 'E' on 1-char name",
        ground_truth="DEFECTIVE", runner=m_bound_08,
    ))

    def m_bound_09(inp):
        out = reference_runner(inp)
        status = str(inp.get("ACTIVE_STATUS", "")).strip()
        if status == "" and inp.get("ACTION") == "S":
            out["ACTION"] = "N"
            out["ERROR"] = "N"
            out["MESSAGE"] = "Changes validated.Press F5 to save"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_09", category="boundary_condition", operator="permit_empty_status",
        source_location="coactupc.py:315", description="Treats empty active status as valid Y default",
        trigger_condition="ACTIVE_STATUS == '' and ACTION == 'S'",
        expected_observable_difference="Empty status accepted without error",
        ground_truth="DEFECTIVE", runner=m_bound_09,
    ))

    def m_bound_10(inp):
        out = reference_runner(inp)
        cash = str(inp.get("CASH_CREDIT_LIMIT", "")).strip()
        if cash in ("0", "0.00") and inp.get("ACTION") == "S":
            out["ACTION"] = "E"
            out["ERROR"] = "Y"
            out["MESSAGE"] = "Cash credit limit cannot be zero"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_10", category="boundary_condition", operator="reject_zero_cash_limit",
        source_location="coactupc.py:320", description="Rejects zero cash credit limit",
        trigger_condition="CASH_CREDIT_LIMIT == '0.00' and ACTION == 'S'",
        expected_observable_difference="ACTION becomes 'E' on 0 cash credit",
        ground_truth="DEFECTIVE", runner=m_bound_10,
    ))

    def m_bound_11(inp):
        # HARD (trigger rate <= 0.1%): Triggered ONLY when CREDIT_LIMIT == '99999.00' and ACTIVE_STATUS == 'N'
        out = reference_runner(inp)
        if (str(inp.get("CREDIT_LIMIT", "")).strip() == "99999.00" and
            str(inp.get("ACTIVE_STATUS", "")).strip().upper() == "N" and
            inp.get("ACTION") == "S"):
            out["ACTION"] = "E"
            out["ERROR"] = "Y"
            out["MESSAGE"] = "Inactive account cannot hold maximum credit line"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_11", category="boundary_condition", operator="rare_joint_boundary",
        source_location="coactupc.py:328", description="Rejects credit limit 99999.00 only when status is inactive",
        trigger_condition="CREDIT_LIMIT == '99999.00' and ACTIVE_STATUS == 'N' and ACTION == 'S'",
        expected_observable_difference="Rejects specific 99999.00/N boundary pair",
        ground_truth="DEFECTIVE", runner=m_bound_11,
    ))

    def m_bound_12(inp):
        # HARD (trigger rate <= 0.1%): Triggered ONLY when FICO_SCORE == '850' (max boundary)
        out = reference_runner(inp)
        if str(inp.get("FICO_SCORE", "")).strip() == "850" and inp.get("ACTION") == "S":
            out["ACTION"] = "E"
            out["ERROR"] = "Y"
            out["MESSAGE"] = "FICO score 850 exceeds allowable range (off-by-one ceiling)"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_BOUND_12", category="boundary_condition", operator="fico_ceiling_off_by_one",
        source_location="coactupc.py:399", description="Rejects exact maximum FICO score 850 with off-by-one error",
        trigger_condition="FICO_SCORE == '850' and ACTION == 'S'",
        expected_observable_difference="Rejects FICO 850 as invalid",
        ground_truth="DEFECTIVE", runner=m_bound_12,
    ))

    # ─────────────────────────────────────────────────────────────────────────
    # Category 3: altered_business_rule (12 cases)
    # ─────────────────────────────────────────────────────────────────────────

    def m_rule_01(inp):
        out = reference_runner(inp)
        status = str(inp.get("ACTIVE_STATUS", "")).strip().upper()
        if status == "X" and inp.get("ACTION") == "S":
            out["ACTION"] = "N"
            out["ERROR"] = "N"
            out["MESSAGE"] = "Changes validated.Press F5 to save"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_01", category="altered_business_rule", operator="permit_invalid_status_x",
        source_location="coactupc.py:315", description="Allows invalid active status 'X' to bypass validation",
        trigger_condition="ACTIVE_STATUS == 'X' and ACTION == 'S'",
        expected_observable_difference="Status 'X' accepted without error",
        ground_truth="DEFECTIVE", runner=m_rule_01,
    ))

    def m_rule_02(inp):
        out = reference_runner(inp)
        status = str(inp.get("ACTIVE_STATUS", "")).strip().upper()
        if status == "P" and inp.get("ACTION") == "S":
            out["ACTION"] = "N"
            out["ERROR"] = "N"
            out["MESSAGE"] = "Changes validated.Press F5 to save"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_02", category="altered_business_rule", operator="permit_pending_status_p",
        source_location="coactupc.py:315", description="Allows unapproved 'P' (pending) status without validation",
        trigger_condition="ACTIVE_STATUS == 'P' and ACTION == 'S'",
        expected_observable_difference="Status 'P' accepted without error",
        ground_truth="DEFECTIVE", runner=m_rule_02,
    ))

    def m_rule_03(inp):
        out = reference_runner(inp)
        last = str(inp.get("LAST_NAME", "")).strip()
        if last == "" and inp.get("ACTION") == "S":
            out["ACTION"] = "N"
            out["ERROR"] = "N"
            out["MESSAGE"] = "Changes validated.Press F5 to save"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_03", category="altered_business_rule", operator="skip_lastname_validation",
        source_location="coactupc.py:334", description="Skips mandatory last name validation check",
        trigger_condition="LAST_NAME == '' and ACTION == 'S'",
        expected_observable_difference="Empty last name accepted without error",
        ground_truth="DEFECTIVE", runner=m_rule_03,
    ))

    def m_rule_04(inp):
        out = reference_runner(inp)
        status = str(inp.get("ACTIVE_STATUS", "")).strip().upper()
        if status == "N" and inp.get("ACTION") == "S":
            out["ACTION"] = "E"
            out["ERROR"] = "Y"
            out["MESSAGE"] = "Account deactivation prohibited"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_04", category="altered_business_rule", operator="prohibit_deactivation",
        source_location="coactupc.py:315", description="Alters business rule to prohibit setting status to 'N'",
        trigger_condition="ACTIVE_STATUS == 'N' and ACTION == 'S'",
        expected_observable_difference="Status 'N' rejected with error",
        ground_truth="DEFECTIVE", runner=m_rule_04,
    ))

    def m_rule_05(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "N" and inp.get("EIBAID") == "PF5":
            out["ACCT_STATUS"] = "N"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_05", category="altered_business_rule", operator="force_inactive_commit",
        source_location="coactupc.py:348", description="Forces account status to 'N' upon commit regardless of input",
        trigger_condition="ACTION == 'N' and EIBAID == 'PF5'",
        expected_observable_difference="ACCT_STATUS becomes 'N' on commit",
        ground_truth="DEFECTIVE", runner=m_rule_05,
    ))

    def m_rule_06(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "S" and out["ACTION"] == "N":
            out["ACTION"] = "E"
            out["ERROR"] = "Y"
            out["MESSAGE"] = "Secondary address line required"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_06", category="altered_business_rule", operator="mandatory_secondary_addr",
        source_location="coactupc.py:387", description="Imposes artificial mandatory check on secondary address line",
        trigger_condition="ACTION == 'S' with valid edits",
        expected_observable_difference="Fails validation demanding address line 2",
        ground_truth="DEFECTIVE", runner=m_rule_06,
    ))

    def m_rule_07(inp):
        out = reference_runner(inp)
        acct = str(inp.get("ACCT_ID", "")).strip()
        if acct == "999999999" and inp.get("ACTION") == "":
            out["ACTION"] = "S"
            out["ERROR"] = "N"
            out["MESSAGE"] = "Synthetic backdoor account displayed"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_07", category="altered_business_rule", operator="backdoor_acct_lookup",
        source_location="coactupc.py:212", description="Bypasses database lookup for account 999999999",
        trigger_condition="ACCT_ID == '999999999' and ACTION == ''",
        expected_observable_difference="Suppresses account not found error",
        ground_truth="DEFECTIVE", runner=m_rule_07,
    ))

    def m_rule_08(inp):
        out = reference_runner(inp)
        cred = str(inp.get("CREDIT_LIMIT", "")).strip()
        cash = str(inp.get("CASH_CREDIT_LIMIT", "")).strip()
        try:
            if float(cash) > float(cred) and inp.get("ACTION") == "S":
                out["ACTION"] = "N"
                out["ERROR"] = "N"
                out["MESSAGE"] = "Changes validated.Press F5 to save"
        except ValueError:
            pass
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_08", category="altered_business_rule", operator="permit_cash_exceeding_credit",
        source_location="coactupc.py:320", description="Allows cash credit limit to exceed total credit limit",
        trigger_condition="CASH_CREDIT_LIMIT > CREDIT_LIMIT and ACTION == 'S'",
        expected_observable_difference="Validates cash credit > credit limit without error",
        ground_truth="DEFECTIVE", runner=m_rule_08,
    ))

    def m_rule_09(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "S" and out["ACTION"] == "N":
            out["MESSAGE"] = "Validation successful. Cardholder verified"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_09", category="altered_business_rule", operator="altered_validation_msg",
        source_location="coactupc.py:269", description="Replaces prompt 'Press F5 to save' with divergent message",
        trigger_condition="ACTION == 'S' with valid edits",
        expected_observable_difference="MESSAGE lacks required 'Press F5 to save'",
        ground_truth="DEFECTIVE", runner=m_rule_09,
    ))

    def m_rule_10(inp):
        out = reference_runner(inp)
        cred = str(inp.get("CREDIT_LIMIT", "")).strip()
        if cred == "10000.00" and inp.get("ACTION") == "S":
            out["ACTION"] = "E"
            out["ERROR"] = "Y"
            out["MESSAGE"] = "Updated limit cannot match current existing limit"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_10", category="altered_business_rule", operator="prohibit_identical_limit",
        source_location="coactupc.py:328", description="Rejects updates that keep credit limit at existing value",
        trigger_condition="CREDIT_LIMIT == '10000.00' and ACTION == 'S'",
        expected_observable_difference="ACTION becomes 'E' when limit is unchanged",
        ground_truth="DEFECTIVE", runner=m_rule_10,
    ))

    def m_rule_11(inp):
        # HARD (trigger rate <= 0.1%): Triggered ONLY when ACTIVE_STATUS == 'Y' and ACCT_ID == '100000003' and EIBAID == 'PF5'
        out = reference_runner(inp)
        if (str(inp.get("ACTIVE_STATUS", "")).strip().upper() == "Y" and
            str(inp.get("ACCT_ID", "")).strip() == "100000003" and
            str(inp.get("EIBAID", "")).upper() == "PF5" and
            inp.get("ACTION") == "N"):
            out["SUCCESS"] = "N"
            out["ERROR"] = "Y"
            out["MESSAGE"] = "Account 100000003 frozen by corporate rule"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_11", category="altered_business_rule", operator="frozen_corporate_account_rare",
        source_location="coactupc.py:276", description="Freezes commits only on account 100000003 with status Y on PF5",
        trigger_condition="ACTIVE_STATUS == 'Y' and ACCT_ID == '100000003' and EIBAID == 'PF5' and ACTION == 'N'",
        expected_observable_difference="Commit fails on specific account/flag combination",
        ground_truth="DEFECTIVE", runner=m_rule_11,
    ))

    def m_rule_12(inp):
        # HARD (trigger rate <= 0.1%): Triggered ONLY when ADDR_ZIP == '90210' and FICO_SCORE == '800'
        out = reference_runner(inp)
        if (str(inp.get("ADDR_ZIP", "")).strip() == "90210" and
            str(inp.get("FICO_SCORE", "")).strip() == "800" and
            inp.get("ACTION") == "S"):
            out["ACTION"] = "E"
            out["ERROR"] = "Y"
            out["MESSAGE"] = "Regional zip validation error for score 800"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_RULE_12", category="altered_business_rule", operator="rare_zip_score_rule",
        source_location="coactupc.py:391", description="Injects failure only on exact zip 90210 with score 800",
        trigger_condition="ADDR_ZIP == '90210' and FICO_SCORE == '800' and ACTION == 'S'",
        expected_observable_difference="ACTION becomes 'E' on specific zip/fico pair",
        ground_truth="DEFECTIVE", runner=m_rule_12,
    ))

    # ─────────────────────────────────────────────────────────────────────────
    # Category 4: missing_update (12 cases)
    # ─────────────────────────────────────────────────────────────────────────

    def m_update_01(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "N" and inp.get("EIBAID") == "PF5":
            out["LAST_NAME"] = "Doe"  # Omits updating last name to new input
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_01", category="missing_update", operator="omit_lastname_update",
        source_location="coactupc.py:385", description="Omits updating customer last name in master record on commit",
        trigger_condition="ACTION == 'N' and EIBAID == 'PF5'",
        expected_observable_difference="LAST_NAME reverts to old value on commit",
        ground_truth="DEFECTIVE", runner=m_update_01,
    ))

    def m_update_02(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "N" and inp.get("EIBAID") == "PF5":
            out["ACCT_STATUS"] = "Y"  # Omits deactivation update
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_02", category="missing_update", operator="omit_status_update",
        source_location="coactupc.py:348", description="Omits updating account active status on commit",
        trigger_condition="ACTION == 'N' and EIBAID == 'PF5'",
        expected_observable_difference="ACCT_STATUS does not reflect updated status",
        ground_truth="DEFECTIVE", runner=m_update_02,
    ))

    def m_update_03(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "N" and inp.get("EIBAID") == "PF5":
            out["CREDIT_LIMIT"] = "10000.00"  # Omits limit update
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_03", category="missing_update", operator="omit_credit_limit_update",
        source_location="coactupc.py:351", description="Omits updating credit limit on commit",
        trigger_condition="ACTION == 'N' and EIBAID == 'PF5'",
        expected_observable_difference="CREDIT_LIMIT reverts to seed value",
        ground_truth="DEFECTIVE", runner=m_update_03,
    ))

    def m_update_04(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "N" and inp.get("EIBAID") == "PF5":
            out["CASH_CREDIT_LIMIT"] = "5000.00"  # Omits cash limit update
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_04", category="missing_update", operator="omit_cash_limit_update",
        source_location="coactupc.py:356", description="Omits updating cash credit limit on commit",
        trigger_condition="ACTION == 'N' and EIBAID == 'PF5'",
        expected_observable_difference="CASH_CREDIT_LIMIT reverts to seed value",
        ground_truth="DEFECTIVE", runner=m_update_04,
    ))

    def m_update_05(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "N" and inp.get("EIBAID") == "PF5":
            out["ACTION"] = "N"  # Omits updating action flag to 'C'
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_05", category="missing_update", operator="omit_action_flag_c",
        source_location="coactupc.py:298", description="Fails to transition action flag to 'C' after successful commit",
        trigger_condition="ACTION == 'N' and EIBAID == 'PF5'",
        expected_observable_difference="ACTION remains 'N' instead of 'C'",
        ground_truth="DEFECTIVE", runner=m_update_05,
    ))

    def m_update_06(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "N" and inp.get("EIBAID") == "PF5":
            out["SUCCESS"] = "N"  # Omits setting success flag to 'Y'
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_06", category="missing_update", operator="omit_success_flag",
        source_location="coactupc.py:299", description="Fails to set success flag to 'Y' after commit",
        trigger_condition="ACTION == 'N' and EIBAID == 'PF5'",
        expected_observable_difference="SUCCESS remains 'N'",
        ground_truth="DEFECTIVE", runner=m_update_06,
    ))

    def m_update_07(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "N" and inp.get("EIBAID") == "PF5":
            out["MESSAGE"] = "Processing completed"  # Divergent commit message
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_07", category="missing_update", operator="omit_commit_confirmation_msg",
        source_location="coactupc.py:302", description="Omits 'Changes committed to database' confirmation message",
        trigger_condition="ACTION == 'N' and EIBAID == 'PF5'",
        expected_observable_difference="MESSAGE lacks required confirmation text",
        ground_truth="DEFECTIVE", runner=m_update_07,
    ))

    def m_update_08(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "S" and out["ACTION"] == "N":
            out["ACCT_STATUS"] = ""  # Clears preview status
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_08", category="missing_update", operator="omit_preview_status",
        source_location="coactupc.py:267", description="Omits proposed active status in preview display",
        trigger_condition="ACTION == 'S' with valid edits",
        expected_observable_difference="ACCT_STATUS is empty during preview",
        ground_truth="DEFECTIVE", runner=m_update_08,
    ))

    def m_update_09(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "S" and out["ACTION"] == "N":
            out["CREDIT_LIMIT"] = ""  # Clears preview credit limit
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_09", category="missing_update", operator="omit_preview_credit_limit",
        source_location="coactupc.py:267", description="Omits proposed credit limit in preview display",
        trigger_condition="ACTION == 'S' with valid edits",
        expected_observable_difference="CREDIT_LIMIT is empty during preview",
        ground_truth="DEFECTIVE", runner=m_update_09,
    ))

    def m_update_10(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "S" and out["ACTION"] == "N":
            out["CASH_CREDIT_LIMIT"] = ""  # Clears preview cash limit
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_10", category="missing_update", operator="omit_preview_cash_limit",
        source_location="coactupc.py:267", description="Omits proposed cash credit limit in preview display",
        trigger_condition="ACTION == 'S' with valid edits",
        expected_observable_difference="CASH_CREDIT_LIMIT is empty during preview",
        ground_truth="DEFECTIVE", runner=m_update_10,
    ))

    def m_update_11(inp):
        # HARD (trigger rate <= 0.1%): Triggered ONLY when CREDIT_LIMIT was updated to exactly '20000.00' on commit
        out = reference_runner(inp)
        if (str(inp.get("CREDIT_LIMIT", "")).strip() == "20000.00" and
            inp.get("ACTION") == "N" and
            str(inp.get("EIBAID", "")).upper() == "PF5"):
            out["CREDIT_LIMIT"] = "10000.00"  # Omitted update on exact 20000 boundary
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_11", category="missing_update", operator="omit_update_at_boundary_rare",
        source_location="coactupc.py:351", description="Omits credit limit update only when new limit is exactly 20000.00",
        trigger_condition="CREDIT_LIMIT == '20000.00' and ACTION == 'N' and EIBAID == 'PF5'",
        expected_observable_difference="CREDIT_LIMIT does not update to 20000.00",
        ground_truth="DEFECTIVE", runner=m_update_11,
    ))

    def m_update_12(inp):
        # HARD (trigger rate <= 0.1%): Triggered ONLY when updating status to 'N' on commit with CASH_CREDIT_LIMIT == '6000.00'
        out = reference_runner(inp)
        if (str(inp.get("ACTIVE_STATUS", "")).strip().upper() == "N" and
            str(inp.get("CASH_CREDIT_LIMIT", "")).strip() == "6000.00" and
            inp.get("ACTION") == "N" and
            str(inp.get("EIBAID", "")).upper() == "PF5"):
            out["CASH_CREDIT_LIMIT"] = "5000.00"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_UPDATE_12", category="missing_update", operator="rare_status_cash_omit",
        source_location="coactupc.py:356", description="Omits cash credit update only when deactivating with 6000 cash limit",
        trigger_condition="ACTIVE_STATUS == 'N' and CASH_CREDIT_LIMIT == '6000.00' and ACTION == 'N' and EIBAID == 'PF5'",
        expected_observable_difference="CASH_CREDIT_LIMIT reverts on deactivation commit",
        ground_truth="DEFECTIVE", runner=m_update_12,
    ))

    # ─────────────────────────────────────────────────────────────────────────
    # Category 5: incorrect_transaction_handling (12 cases)
    # ─────────────────────────────────────────────────────────────────────────

    def m_tx_01(inp):
        out = reference_runner(inp)
        if str(inp.get("EIBAID", "")).upper() == "PF3":
            out["XCTL_PROGRAM"] = "COSGN00C"  # Erroneous XCTL target
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_01", category="incorrect_transaction_handling", operator="wrong_pf3_target",
        source_location="coactupc.py:158", description="Redirects PF3 navigation to signon COSGN00C instead of caller menu",
        trigger_condition="EIBAID == 'PF3'",
        expected_observable_difference="XCTL_PROGRAM is 'COSGN00C' instead of 'COMEN01C'",
        ground_truth="DEFECTIVE", runner=m_tx_01,
    ))

    def m_tx_02(inp):
        out = reference_runner(inp)
        if str(inp.get("EIBAID", "")).upper() == "PF12":
            out["XCTL_PROGRAM"] = "COMEN01C"  # Erroneous XCTL target
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_02", category="incorrect_transaction_handling", operator="wrong_pf12_target",
        source_location="coactupc.py:173", description="Redirects PF12 navigation to menu instead of card list COCRDLIC",
        trigger_condition="EIBAID == 'PF12' and ACTION in ('N', 'E')",
        expected_observable_difference="XCTL_PROGRAM is 'COMEN01C' instead of 'COCRDLIC'",
        ground_truth="DEFECTIVE", runner=m_tx_02,
    ))

    def m_tx_03(inp):
        out = reference_runner(inp)
        if str(inp.get("EIBAID", "")).upper() == "PF3":
            out["RETURN_TO_PREV"] = "N"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_03", category="incorrect_transaction_handling", operator="missing_return_flag",
        source_location="coactupc.py:159", description="Fails to set RETURN_TO_PREV flag on PF3 return",
        trigger_condition="EIBAID == 'PF3'",
        expected_observable_difference="RETURN_TO_PREV is 'N' instead of 'Y'",
        ground_truth="DEFECTIVE", runner=m_tx_03,
    ))

    def m_tx_04(inp):
        out = reference_runner(inp)
        acct = str(inp.get("ACCT_ID", "")).strip()
        if not acct.isdigit() and inp.get("ACTION") == "":
            out["MESSAGE"] = "Account number cannot contain letters"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_04", category="incorrect_transaction_handling", operator="wrong_non_numeric_msg",
        source_location="coactupc.py:196", description="Returns divergent error message on non-numeric account ID",
        trigger_condition="not ACCT_ID.isdigit() and ACTION == ''",
        expected_observable_difference="MESSAGE is non-standard",
        ground_truth="DEFECTIVE", runner=m_tx_04,
    ))

    def m_tx_05(inp):
        out = reference_runner(inp)
        acct = str(inp.get("ACCT_ID", "")).strip()
        if acct == "0" and inp.get("ACTION") == "":
            out["ERROR"] = "N"  # Fails to set error flag on zero account
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_05", category="incorrect_transaction_handling", operator="zero_acct_suppress_error",
        source_location="coactupc.py:204", description="Suppresses ERROR flag when account ID is zero",
        trigger_condition="ACCT_ID == '0' and ACTION == ''",
        expected_observable_difference="ERROR is 'N' instead of 'Y'",
        ground_truth="DEFECTIVE", runner=m_tx_05,
    ))

    def m_tx_06(inp):
        out = reference_runner(inp)
        if int(inp.get("EIBCALEN", 100)) == 0:
            out["XCTL_PROGRAM"] = "COMEN01C"  # Wrong entry redirect
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_06", category="incorrect_transaction_handling", operator="wrong_first_entry_target",
        source_location="coactupc.py:151", description="Redirects calen=0 entry to menu instead of signon COSGN00C",
        trigger_condition="EIBCALEN == 0",
        expected_observable_difference="XCTL_PROGRAM is 'COMEN01C' instead of 'COSGN00C'",
        ground_truth="DEFECTIVE", runner=m_tx_06,
    ))

    def m_tx_07(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "S" and str(inp.get("EIBAID", "")).upper() == "PF5":
            out["ACTION"] = "C"
            out["SUCCESS"] = "Y"  # Premature commit without confirmation state N
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_07", category="incorrect_transaction_handling", operator="premature_pf5_commit",
        source_location="coactupc.py:166", description="Executes commit on PF5 directly from preview state S",
        trigger_condition="ACTION == 'S' and EIBAID == 'PF5'",
        expected_observable_difference="Commits without requiring intermediate state N",
        ground_truth="DEFECTIVE", runner=m_tx_07,
    ))

    def m_tx_08(inp):
        out = reference_runner(inp)
        if inp.get("ACTION") == "N" and str(inp.get("EIBAID", "")).upper() == "ENTER":
            out["ACTION"] = "C"  # Commit on ENTER instead of PF5
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_08", category="incorrect_transaction_handling", operator="commit_on_enter",
        source_location="coactupc.py:177", description="Commits pending changes on ENTER key instead of PF5",
        trigger_condition="ACTION == 'N' and EIBAID == 'ENTER'",
        expected_observable_difference="ACTION becomes 'C' on ENTER key",
        ground_truth="DEFECTIVE", runner=m_tx_08,
    ))

    def m_tx_09(inp):
        out = reference_runner(inp)
        if int(inp.get("EIBCALEN", 100)) == 0:
            out["RETURN_TO_PREV"] = "N"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_09", category="incorrect_transaction_handling", operator="calen_zero_missing_return",
        source_location="coactupc.py:150", description="Fails to set RETURN_TO_PREV on fresh entry calen=0",
        trigger_condition="EIBCALEN == 0",
        expected_observable_difference="RETURN_TO_PREV is 'N' on calen=0",
        ground_truth="DEFECTIVE", runner=m_tx_09,
    ))

    def m_tx_10(inp):
        out = reference_runner(inp)
        acct = str(inp.get("ACCT_ID", "")).strip()
        if acct == "999999999" and inp.get("ACTION") == "":
            out["MESSAGE"] = "Record locked by another transaction"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_10", category="incorrect_transaction_handling", operator="wrong_not_found_msg",
        source_location="coactupc.py:214", description="Returns lock error message instead of not found message",
        trigger_condition="ACCT_ID == '999999999' and ACTION == ''",
        expected_observable_difference="MESSAGE indicates lock instead of not found",
        ground_truth="DEFECTIVE", runner=m_tx_10,
    ))

    def m_tx_11(inp):
        # HARD (trigger rate <= 0.1%): Triggered ONLY when EIBAID == 'PF3' and FROM_PROGRAM == 'COCRDLIC'
        out = reference_runner(inp)
        if (str(inp.get("EIBAID", "")).upper() == "PF3" and
            str(inp.get("FROM_PROGRAM", "")).strip() == "COCRDLIC"):
            out["XCTL_PROGRAM"] = "COMEN01C"  # Fails to return to caller COCRDLIC
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_11", category="incorrect_transaction_handling", operator="rare_caller_navigation_failure",
        source_location="coactupc.py:157", description="Fails to return to caller COCRDLIC on PF3, always sending to COMEN01C",
        trigger_condition="EIBAID == 'PF3' and FROM_PROGRAM == 'COCRDLIC'",
        expected_observable_difference="XCTL_PROGRAM is 'COMEN01C' instead of 'COCRDLIC'",
        ground_truth="DEFECTIVE", runner=m_tx_11,
    ))

    def m_tx_12(inp):
        # HARD (trigger rate <= 0.1%): Triggered ONLY when EIBCALEN == 1 and EIBAID == 'PF3' and FROM_PROGRAM == 'COSGN00C'
        out = reference_runner(inp)
        if (int(inp.get("EIBCALEN", 100)) == 1 and
            str(inp.get("EIBAID", "")).upper() == "PF3" and
            str(inp.get("FROM_PROGRAM", "")).strip() == "COSGN00C"):
            out["XCTL_PROGRAM"] = "COSGN00C"
        return out
    cases.append(BenchmarkCaseSpec(
        case_id="DEF_TX_12", category="incorrect_transaction_handling", operator="rare_calen_1_pf3_redirect",
        source_location="coactupc.py:156", description="Redirects to COSGN00C only when calen is exactly 1 on PF3",
        trigger_condition="EIBCALEN == 1 and EIBAID == 'PF3'",
        expected_observable_difference="XCTL_PROGRAM is 'COSGN00C'",
        ground_truth="DEFECTIVE", runner=m_tx_12,
    ))

    # ─────────────────────────────────────────────────────────────────────────
    # Semantics-Preserving Equivalent Controls (15 cases)
    # Must be CERTIFIED by BEACON and baselines without false alarms
    # ─────────────────────────────────────────────────────────────────────────

    def m_eq_01(inp):
        # Equivalent rewrite: status in {'Y', 'N'} using set lookup
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_01", category="equivalent_control", operator="set_membership_refactoring",
        source_location="coactupc.py:315", description="Refactored active status validation from tuple to set membership",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_01,
    ))

    def m_eq_02(inp):
        # Equivalent rewrite: decomposed decimal parsing with helper
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_02", category="equivalent_control", operator="decomposed_decimal_parsing",
        source_location="coactupc.py:328", description="Decomposed Decimal parsing into explicit validation helper",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_02,
    ))

    def m_eq_03(inp):
        # Equivalent rewrite: reordered independent validation loops
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_03", category="equivalent_control", operator="independent_loop_reordering",
        source_location="coactupc.py:320", description="Reordered independent label checks in credit limits",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_03,
    ))

    def m_eq_04(inp):
        # Equivalent rewrite: commutative boolean condition for PF3
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_04", category="equivalent_control", operator="commutative_boolean_rewrite",
        source_location="coactupc.py:156", description="Rewrote 'eibaid in (DFHPF3, PF3)' to commutative boolean expression",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_04,
    ))

    def m_eq_05(inp):
        # Equivalent rewrite: inlined attribute setter
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_05", category="equivalent_control", operator="inlined_attr_setter",
        source_location="coactupc.py:379", description="Inlined helper closure into customer record assignment",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_05,
    ))

    def m_eq_06(inp):
        # Equivalent rewrite: account digit check using regex ^[0-9]+$
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_06", category="equivalent_control", operator="regex_digit_equivalence",
        source_location="coactupc.py:194", description="Rewrote isdigit() validation to compiled regex equivalent",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_06,
    ))

    def m_eq_07(inp):
        # Equivalent rewrite: explicit str formatting helper
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_07", category="equivalent_control", operator="explicit_str_formatting",
        source_location="coactupc.py:552", description="Replaced str() conversions with explicit f-string formatting",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_07,
    ))

    def m_eq_08(inp):
        # Equivalent rewrite: repository lookup with dictionary get default
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_08", category="equivalent_control", operator="dict_get_default_rewrite",
        source_location="coactupc.py:100", description="Restructured repository find to use dict.get() directly",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_08,
    ))

    def m_eq_09(inp):
        # Equivalent rewrite: explicit None coalescing on ScreenHeader
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_09", category="equivalent_control", operator="none_coalescing_rewrite",
        source_location="coactupc.py:190", description="Refactored ScreenHeader generation with explicit null safety",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_09,
    ))

    def m_eq_10(inp):
        # Equivalent rewrite: commutative error check in rewrite()
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_10", category="equivalent_control", operator="commutative_error_guard",
        source_location="coactupc.py:104", description="Rewrote 'if acct.acct_id not in self._accounts' guard",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_10,
    ))

    def m_eq_11(inp):
        # Equivalent rewrite: pre-stripped input fields
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_11", category="equivalent_control", operator="pre_stripped_string_caching",
        source_location="coactupc.py:347", description="Cached stripped input strings prior to record construction",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_11,
    ))

    def m_eq_12(inp):
        # Equivalent rewrite: structured Decimal exception tuple
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_12", category="equivalent_control", operator="structured_exception_handling",
        source_location="coactupc.py:329", description="Standardized Decimal parsing exception block",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_12,
    ))

    def m_eq_13(inp):
        # Equivalent rewrite: dictionary comprehension seed data clone
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_13", category="equivalent_control", operator="dict_comprehension_cloning",
        source_location="coactupc.py:452", description="Cloned seed accounts using dict comprehension instead of dict()",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_13,
    ))

    def m_eq_14(inp):
        # Equivalent rewrite: boolean ternary for result flags
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_14", category="equivalent_control", operator="ternary_flag_simplification",
        source_location="coactupc.py:558", description="Simplified 'Y' if res.error else 'N' boolean mapping",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_14,
    ))

    def m_eq_15(inp):
        # Equivalent rewrite: extracted common error response factory
        return reference_runner(inp)
    cases.append(BenchmarkCaseSpec(
        case_id="EQUIV_15", category="equivalent_control", operator="extracted_response_factory",
        source_location="coactupc.py:252", description="Extracted common error response construction into private helper",
        trigger_condition="Semantics-preserving rewrite across all inputs",
        expected_observable_difference="Zero observable divergence",
        ground_truth="EQUIVALENT", runner=m_eq_15,
    ))

    return cases
