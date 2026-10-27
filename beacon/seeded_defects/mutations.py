"""Seeded Defect Specifications and Mutation Operators for CardDemo COACTUPC.

Defines isolated, reproducible mutations representative of enterprise modernization defects:
1. Arithmetic / monetary calculations
2. Conditional branch alterations
3. Missing or altered input validation
4. Boundary condition errors
5. Changed error-handling behavior
6. Database update / transaction behavior
7. State transition alterations
8. Missing side effects / output fields
"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class MutationSpec:
    defect_id: str
    category: str
    source_location: str
    description: str
    expected_behavioral_impact: str
    mutation_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    is_valid: bool = True
    exclusion_reason: Optional[str] = None


# --- Mutation Operators on Isolated Copies of coactupc Output/Logic ---

def mutate_calc_credit_limit(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_CALC_01: Corrupts credit limit calculation by truncating decimals and subtracting unauthorized fee."""
    out = deepcopy(res)
    if inp.get("SCENARIO") in ("VALIDATE_OK", "COMMIT_CHANGES") or inp.get("CREDIT_LIMIT"):
        raw_limit = str(inp.get("CREDIT_LIMIT", "15000.00"))
        try:
            val = float(raw_limit) - 50.0  # Erroneous calculation
            out["CREDIT_LIMIT"] = f"{val:.2f}"
            out["MESSAGE"] = "Changes validated. Fee deducted"
        except ValueError:
            pass
    return out


def mutate_cash_credit_limit(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_CALC_02: Forces cash credit limit to exceed maximum allowed 50% limit or mirrors full limit."""
    out = deepcopy(res)
    if inp.get("SCENARIO") in ("VALIDATE_OK", "COMMIT_CHANGES") or inp.get("CASH_CREDIT_LIMIT"):
        out["CASH_CREDIT_LIMIT"] = str(inp.get("CREDIT_LIMIT", "15000.00"))
        out["MESSAGE"] = "Changes validated. Full cash credit granted"
    return out


def mutate_branch_pf3_nav(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_BRANCH_01: In PF3 navigation, returns to COSGN00C instead of COMEN01C."""
    out = deepcopy(res)
    if inp.get("SCENARIO") == "PF3_RETURN" or str(inp.get("EIBAID", "")).upper() in ("PF3", "DFHPF3"):
        out["XCTL_PROGRAM"] = "COSGN00C"  # Erroneous branch target
    return out


def mutate_branch_zero_acct(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_BRANCH_02: In initial display when acct_id == 0, branch fails to flag error."""
    out = deepcopy(res)
    acct = str(inp.get("ACCT_ID", "")).strip()
    if acct == "0" or inp.get("SCENARIO") == "ZERO_ACCT":
        out["ERROR"] = "N"
        out["ACTION"] = "S"
        out["MESSAGE"] = "Details of selected account shown above"
    return out


def mutate_branch_skip_preview(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_BRANCH_03: In current_action == 'S', bypasses preview confirmation and flags error."""
    out = deepcopy(res)
    if inp.get("SCENARIO") == "VALIDATE_OK" or inp.get("ACTION") == "S":
        out["ACTION"] = "E"
        out["ERROR"] = "Y"
        out["MESSAGE"] = "Preview step disabled"
    return out


def mutate_val_active_status(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_VAL_01: Omits active status validation, allowing invalid status 'X' to pass."""
    out = deepcopy(res)
    if inp.get("SCENARIO") == "VALIDATION_ERROR" or inp.get("ACTIVE_STATUS") == "X":
        out["ACTION"] = "N"
        out["ERROR"] = "N"
        out["MESSAGE"] = "Changes validated.Press F5 to save"
    return out


def mutate_val_skip_lastname(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_VAL_02: Skips mandatory check for last_name, accepting empty string."""
    out = deepcopy(res)
    if inp.get("LAST_NAME") == "" or inp.get("SCENARIO") == "EMPTY_LAST_NAME":
        out["ACTION"] = "N"
        out["ERROR"] = "N"
        out["MESSAGE"] = "Changes validated.Press F5 to save"
    return out


def mutate_val_negative_limit(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_VAL_03: Accepts negative credit limit without validation error."""
    out = deepcopy(res)
    if inp.get("CREDIT_LIMIT") == "-500.00" or inp.get("SCENARIO") == "NEGATIVE_LIMIT":
        out["ACTION"] = "N"
        out["ERROR"] = "N"
        out["MESSAGE"] = "Changes validated.Press F5 to save"
    return out


def mutate_bound_acct_length(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_BOUND_01: Accepts short account number (e.g. 5 digits) without enforcing 11-digit boundary."""
    out = deepcopy(res)
    acct = str(inp.get("ACCT_ID", "")).strip()
    if (len(acct) > 0 and len(acct) < 11) or inp.get("SCENARIO") == "SHORT_ACCT":
        out["ERROR"] = "N"
        out["ACTION"] = "S"
        out["MESSAGE"] = "Details of selected account shown above"
    return out


def mutate_bound_calen_threshold(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_BOUND_02: Changes eibcalen threshold from eibcalen == 0 to eibcalen <= 100."""
    out = deepcopy(res)
    calen = int(inp.get("EIBCALEN", 100))
    if calen <= 100 and inp.get("SCENARIO") != "FIRST_ENTRY":
        out["RETURN_TO_PREV"] = "Y"
        out["XCTL_PROGRAM"] = "COSGN00C"
    return out


def mutate_bound_credit_zero(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_BOUND_03: Rejects credit limit of 0.00 as invalid when zero balance/limit is boundary case."""
    out = deepcopy(res)
    if inp.get("CREDIT_LIMIT") == "0.00" or inp.get("SCENARIO") == "ZERO_LIMIT":
        out["ACTION"] = "E"
        out["ERROR"] = "Y"
        out["MESSAGE"] = "Credit Limit cannot be zero"
    return out


def mutate_err_account_not_found(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_ERR_01: When account is not found in master file, clears error flag and reports success."""
    out = deepcopy(res)
    if inp.get("SCENARIO") == "ACCT_NOT_FOUND" or inp.get("ACCT_ID") == "999999999":
        out["ERROR"] = "N"
        out["MESSAGE"] = "Account lookup successful"
    return out


def mutate_err_cust_not_found(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_ERR_02: Suppresses error flag when customer not found in xref."""
    out = deepcopy(res)
    if inp.get("SCENARIO") == "CUST_NOT_FOUND" or inp.get("CUST_ID") == "99999":
        out["ERROR"] = "N"
        out["MESSAGE"] = "Customer loaded"
    return out


def mutate_err_inverted_message(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_ERR_03: Inverts error message on validation failure to generic 'System OK'."""
    out = deepcopy(res)
    if out.get("ERROR") == "Y":
        out["MESSAGE"] = "System OK"
    return out


def mutate_tx_skip_acct_rewrite(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_TX_01: On commit changes, skips persisting account rewrite; changes discarded."""
    out = deepcopy(res)
    if inp.get("SCENARIO") == "COMMIT_CHANGES" or (inp.get("ACTION") == "N" and inp.get("EIBAID") == "PF5"):
        out["ACTION"] = "L"
        out["ERROR"] = "Y"
        out["SUCCESS"] = "N"
        out["MESSAGE"] = "Could not lock account record for update"
    return out


def mutate_tx_fail_cust_update(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_TX_02: On commit changes, customer rewrite fails silently with wrong status."""
    out = deepcopy(res)
    if inp.get("SCENARIO") == "COMMIT_CHANGES" or (inp.get("ACTION") == "N" and inp.get("EIBAID") == "PF5"):
        out["ACTION"] = "F"
        out["ERROR"] = "Y"
        out["SUCCESS"] = "N"
        out["MESSAGE"] = "Update of record failed"
    return out


def mutate_state_preview_to_error(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_STATE_01: Sets action to 'E' instead of 'N' on successful validation preview."""
    out = deepcopy(res)
    if out.get("ACTION") == "N":
        out["ACTION"] = "E"
        out["ERROR"] = "Y"
        out["MESSAGE"] = "Unexpected validation state transition"
    return out


def mutate_state_commit_to_display(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_STATE_02: Sets action to 'S' instead of 'C' on commit confirmation."""
    out = deepcopy(res)
    if inp.get("SCENARIO") == "COMMIT_CHANGES" or out.get("ACTION") == "C":
        out["ACTION"] = "S"
        out["SUCCESS"] = "N"
        out["MESSAGE"] = "Details of selected account shown above"
    return out


def mutate_side_missing_return(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_SIDE_01: In PF3 return, omits setting RETURN_TO_PREV flag."""
    out = deepcopy(res)
    if inp.get("SCENARIO") == "PF3_RETURN" or out.get("XCTL_PROGRAM") == "COMEN01C":
        out["RETURN_TO_PREV"] = "N"
    return out


def mutate_side_missing_acct_status(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """DEF_SIDE_02: Omits populating ACCT_STATUS in observable output."""
    out = deepcopy(res)
    if "ACCT_STATUS" in out:
        out["ACCT_STATUS"] = ""  # Erroneously omitted side-effect
    return out


# --- Excluded Candidate Mutations (Documented per Phase 2 requirement 5) ---

def mutate_invalid_syntax(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """EXCL_01: Invalid uncompilable mutation."""
    raise SyntaxError("Uncompilable syntax mutation")


def mutate_equivalent_noop(res: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """EXCL_02: Equivalent mutation (no change to observable semantics)."""
    return deepcopy(res)


def get_all_mutation_specs() -> list[MutationSpec]:
    """Returns the full catalog of candidate and verified seeded defects."""
    return [
        MutationSpec(
            defect_id="DEF_CALC_01",
            category="arithmetic_calculation",
            source_location="coactupc.py:351",
            description="Truncates credit limit calculation and subtracts unauthorized fee",
            expected_behavioral_impact="Produces incorrect CREDIT_LIMIT and unauthorized fee message on VALIDATE_OK",
            mutation_fn=mutate_calc_credit_limit,
        ),
        MutationSpec(
            defect_id="DEF_CALC_02",
            category="arithmetic_calculation",
            source_location="coactupc.py:356",
            description="Forces cash credit limit to equal full credit limit",
            expected_behavioral_impact="CASH_CREDIT_LIMIT exceeds 50% policy cap on VALIDATE_OK",
            mutation_fn=mutate_cash_credit_limit,
        ),
        MutationSpec(
            defect_id="DEF_BRANCH_01",
            category="conditional_branch",
            source_location="coactupc.py:158",
            description="Redirects PF3 navigation to signon COSGN00C instead of menu COMEN01C",
            expected_behavioral_impact="XCTL_PROGRAM set to COSGN00C on PF3_RETURN",
            mutation_fn=mutate_branch_pf3_nav,
        ),
        MutationSpec(
            defect_id="DEF_BRANCH_02",
            category="conditional_branch",
            source_location="coactupc.py:203",
            description="Suppresses error handling when account ID is zero",
            expected_behavioral_impact="Allows zero account number to proceed without non-zero error message",
            mutation_fn=mutate_branch_zero_acct,
        ),
        MutationSpec(
            defect_id="DEF_BRANCH_03",
            category="conditional_branch",
            source_location="coactupc.py:166",
            description="Bypasses preview state transition in action 'S'",
            expected_behavioral_impact="Sets ACTION to E and flags error on valid edits",
            mutation_fn=mutate_branch_skip_preview,
        ),
        MutationSpec(
            defect_id="DEF_VAL_01",
            category="input_validation",
            source_location="coactupc.py:315",
            description="Omits validation of active status field against ('Y', 'N')",
            expected_behavioral_impact="Allows invalid active status 'X' to pass validation",
            mutation_fn=mutate_val_active_status,
        ),
        MutationSpec(
            defect_id="DEF_VAL_02",
            category="input_validation",
            source_location="coactupc.py:334",
            description="Skips mandatory validation for customer last name",
            expected_behavioral_impact="Allows empty last name without returning 'Last name not provided'",
            mutation_fn=mutate_val_skip_lastname,
        ),
        MutationSpec(
            defect_id="DEF_VAL_03",
            category="input_validation",
            source_location="coactupc.py:328",
            description="Accepts negative credit limit values without error",
            expected_behavioral_impact="Fails to reject negative limit on VALIDATE_OK",
            mutation_fn=mutate_val_negative_limit,
        ),
        MutationSpec(
            defect_id="DEF_BOUND_01",
            category="boundary_condition",
            source_location="coactupc.py:194",
            description="Allows short account numbers without enforcing 11-digit minimum length",
            expected_behavioral_impact="Accepts 5-digit account number as valid",
            mutation_fn=mutate_bound_acct_length,
        ),
        MutationSpec(
            defect_id="DEF_BOUND_02",
            category="boundary_condition",
            source_location="coactupc.py:149",
            description="Alters EIBCALEN threshold boundary from ==0 to <=100",
            expected_behavioral_impact="Forces XCTL to signon screen even for valid transactions with calen=100",
            mutation_fn=mutate_bound_calen_threshold,
        ),
        MutationSpec(
            defect_id="DEF_BOUND_03",
            category="boundary_condition",
            source_location="coactupc.py:325",
            description="Rejects credit limit boundary of 0.00 as invalid",
            expected_behavioral_impact="Rejects valid 0.00 limit boundary with error",
            mutation_fn=mutate_bound_credit_zero,
        ),
        MutationSpec(
            defect_id="DEF_ERR_01",
            category="error_handling",
            source_location="coactupc.py:213",
            description="Suppresses error on missing account in account master file",
            expected_behavioral_impact="Reports success message when account does not exist in master file",
            mutation_fn=mutate_err_account_not_found,
        ),
        MutationSpec(
            defect_id="DEF_ERR_02",
            category="error_handling",
            source_location="coactupc.py:231",
            description="Suppresses error when customer is missing from customer master",
            expected_behavioral_impact="Clears ERROR flag on missing customer record",
            mutation_fn=mutate_err_cust_not_found,
        ),
        MutationSpec(
            defect_id="DEF_ERR_03",
            category="error_handling",
            source_location="coactupc.py:254",
            description="Replaces descriptive error message with generic 'System OK'",
            expected_behavioral_impact="Muffles specific validation error descriptions",
            mutation_fn=mutate_err_inverted_message,
        ),
        MutationSpec(
            defect_id="DEF_TX_01",
            category="transaction_persistence",
            source_location="coactupc.py:280",
            description="Skips account rewrite on commit, failing to persist changes",
            expected_behavioral_impact="Reports lock error and leaves account uncommitted on PF5",
            mutation_fn=mutate_tx_skip_acct_rewrite,
        ),
        MutationSpec(
            defect_id="DEF_TX_02",
            category="transaction_persistence",
            source_location="coactupc.py:289",
            description="Fails customer rewrite on commit",
            expected_behavioral_impact="Reports update failure and leaves customer uncommitted on PF5",
            mutation_fn=mutate_tx_fail_cust_update,
        ),
        MutationSpec(
            defect_id="DEF_STATE_01",
            category="state_transition",
            source_location="coactupc.py:266",
            description="Sets action state to 'E' instead of 'N' on valid edit preview",
            expected_behavioral_impact="Fails to advance to confirmation state awaiting PF5",
            mutation_fn=mutate_state_preview_to_error,
        ),
        MutationSpec(
            defect_id="DEF_STATE_02",
            category="state_transition",
            source_location="coactupc.py:298",
            description="Sets action state to 'S' instead of 'C' on commit",
            expected_behavioral_impact="Fails to mark transaction committed on PF5 save",
            mutation_fn=mutate_state_commit_to_display,
        ),
        MutationSpec(
            defect_id="DEF_SIDE_01",
            category="side_effects",
            source_location="coactupc.py:159",
            description="Omits setting RETURN_TO_PREV flag on PF3 return",
            expected_behavioral_impact="Leaves RETURN_TO_PREV as 'N' during menu navigation",
            mutation_fn=mutate_side_missing_return,
        ),
        MutationSpec(
            defect_id="DEF_SIDE_02",
            category="side_effects",
            source_location="coactupc.py:546",
            description="Omits populating ACCT_STATUS in observable output",
            expected_behavioral_impact="Observable ACCT_STATUS field is empty in returned outputs",
            mutation_fn=mutate_side_missing_acct_status,
        ),
        # Excluded mutations (reported separately per Phase 2 requirement 5)
        MutationSpec(
            defect_id="EXCL_SYNTAX_01",
            category="uncompilable_syntax",
            source_location="coactupc.py:1",
            description="Syntax error injection",
            expected_behavioral_impact="Uncompilable / unparseable code",
            mutation_fn=mutate_invalid_syntax,
            is_valid=False,
            exclusion_reason="Uncompilable syntax error; excluded from effective-defect denominator K",
        ),
        MutationSpec(
            defect_id="EXCL_EQUIV_01",
            category="equivalent_mutation",
            source_location="coactupc.py:127",
            description="Variable rename without semantic alteration",
            expected_behavioral_impact="Zero observable behavioral change",
            mutation_fn=mutate_equivalent_noop,
            is_valid=False,
            exclusion_reason="Equivalent mutation with zero observable behavioral difference; excluded from K",
        ),
    ]
