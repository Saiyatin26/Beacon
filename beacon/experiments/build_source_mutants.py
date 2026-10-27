"""Builds 76 Genuine Source-Level Candidate Implementations for CardDemo COACTUPC.

Generates actual Python source files in experiments/mutants/:
- 60 Defective candidate variants across 5 categories
- 15 Semantics-preserving equivalent refactored candidate variants
- 1 Clean candidate variant (CTRL_00)

Every mutant is a standalone source file with verifiable line changes,
compiler validation, and SHA-256 cryptographic digests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import py_compile
import re
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
CANONICAL_SOURCE_PATH = BASE_DIR / "data" / "staged_sources" / "modern" / "coactupc.py"
MUTANTS_DIR = BASE_DIR / "experiments" / "mutants"
MUTANTS_DIR.mkdir(parents=True, exist_ok=True)


def load_canonical_source() -> str:
    return CANONICAL_SOURCE_PATH.read_text(encoding="utf-8")


def sha256_str(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply_replacement(source: str, old: str, new: str, desc: str) -> str:
    if old not in source:
        raise ValueError(f"Target pattern not found for replacement: {desc}\nPattern: {old[:60]}...")
    return source.replace(old, new, 1)


def generate_all_mutants() -> list[dict]:
    canonical_source = load_canonical_source()
    canonical_hash = sha256_str(canonical_source)
    mutant_records = []

    # ── Clean Control 00 ──
    mutant_records.append({
        "case_id": "CTRL_00",
        "category": "clean_control",
        "operator": "identity",
        "source_file": "experiments/mutants/candidate_CTRL_00.py",
        "changed_function": "None",
        "changed_line": "1-567",
        "description": "Clean unmodified candidate modernization",
        "trigger_condition": "None",
        "expected_observable_difference": "None (Strict equivalence)",
        "ground_truth": "EQUIVALENT",
        "source_code": canonical_source,
    })

    # ─────────────────────────────────────────────────────────────────────────
    # Category 1: incorrect_calculation (12 cases)
    # ─────────────────────────────────────────────────────────────────────────

    # DEF_CALC_01: Unauthorized $50 fee deduction on credit limit
    code = apply_replacement(
        canonical_source,
        'acct.acct_credit_limit = Decimal(inp.credit_limit.strip())',
        'acct.acct_credit_limit = Decimal(inp.credit_limit.strip()) - Decimal("50.00")',
        "DEF_CALC_01",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_01", "category": "incorrect_calculation", "operator": "unauthorized_fee_deduction",
        "source_file": "experiments/mutants/candidate_DEF_CALC_01.py",
        "changed_function": "_apply_acct_input", "changed_line": "351",
        "description": "Deducts unauthorized $50 fee from validated credit limit",
        "trigger_condition": "ACTION == 'S' with valid edits",
        "expected_observable_difference": "CREDIT_LIMIT is $50 less than expected",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_CALC_02: Balance inflation by $10
    code = apply_replacement(
        canonical_source,
        'acct.acct_curr_bal = Decimal(inp.curr_bal.strip())',
        'acct.acct_curr_bal = Decimal(inp.curr_bal.strip()) + Decimal("10.00")',
        "DEF_CALC_02",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_02", "category": "incorrect_calculation", "operator": "balance_inflation",
        "source_file": "experiments/mutants/candidate_DEF_CALC_02.py",
        "changed_function": "_apply_acct_input", "changed_line": "361",
        "description": "Inflates account current balance by $10",
        "trigger_condition": "ACTION == 'S' with valid edits and non-empty CURR_BAL",
        "expected_observable_difference": "ACCT_BAL is $10 greater than expected",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_CALC_03: Cash limit truncation to 90%
    code = apply_replacement(
        canonical_source,
        'acct.acct_cash_credit_limit = Decimal(inp.cash_credit_limit.strip())',
        'acct.acct_cash_credit_limit = (Decimal(inp.cash_credit_limit.strip()) * Decimal("0.90")).quantize(Decimal("0.01"))',
        "DEF_CALC_03",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_03", "category": "incorrect_calculation", "operator": "cash_limit_truncation",
        "source_file": "experiments/mutants/candidate_DEF_CALC_03.py",
        "changed_function": "_apply_acct_input", "changed_line": "356",
        "description": "Applies incorrect 10% penalty reduction to cash credit limit",
        "trigger_condition": "ACTION == 'S' with valid edits and non-empty CASH_CREDIT_LIMIT",
        "expected_observable_difference": "CASH_CREDIT_LIMIT is 90% of expected value",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_CALC_04: 5% surcharge added to credit limit
    code = apply_replacement(
        canonical_source,
        'acct.acct_credit_limit = Decimal(inp.credit_limit.strip())',
        'acct.acct_credit_limit = (Decimal(inp.credit_limit.strip()) * Decimal("1.05")).quantize(Decimal("0.01"))',
        "DEF_CALC_04",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_04", "category": "incorrect_calculation", "operator": "surcharge_addition",
        "source_file": "experiments/mutants/candidate_DEF_CALC_04.py",
        "changed_function": "_apply_acct_input", "changed_line": "351",
        "description": "Adds unauthorized 5% surcharge to credit limit",
        "trigger_condition": "ACTION == 'S' with valid edits",
        "expected_observable_difference": "CREDIT_LIMIT is 105% of input value",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_CALC_05: Integer truncation of cash limit
    code = apply_replacement(
        canonical_source,
        'acct.acct_cash_credit_limit = Decimal(inp.cash_credit_limit.strip())',
        'acct.acct_cash_credit_limit = Decimal(int(Decimal(inp.cash_credit_limit.strip()))).quantize(Decimal("0.01"))',
        "DEF_CALC_05",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_05", "category": "incorrect_calculation", "operator": "fractional_cent_truncation",
        "source_file": "experiments/mutants/candidate_DEF_CALC_05.py",
        "changed_function": "_apply_acct_input", "changed_line": "356",
        "description": "Truncates fractional cents from cash credit limit",
        "trigger_condition": "ACTION == 'S' and CASH_CREDIT_LIMIT contains fractional cents",
        "expected_observable_difference": "CASH_CREDIT_LIMIT cents truncated to .00",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_CALC_06: FICO penalty deduction of 25 points
    code = apply_replacement(
        canonical_source,
        'cust.cust_fico_credit_score = int(inp.fico_score.strip())',
        'cust.cust_fico_credit_score = int(inp.fico_score.strip()) - 25',
        "DEF_CALC_06",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_06", "category": "incorrect_calculation", "operator": "fico_score_offset",
        "source_file": "experiments/mutants/candidate_DEF_CALC_06.py",
        "changed_function": "_apply_cust_input", "changed_line": "400",
        "description": "Subtracts 25 points from customer FICO score",
        "trigger_condition": "ACTION == 'S' with valid edits and FICO_SCORE provided",
        "expected_observable_difference": "FICO_SCORE updated with incorrect -25 offset",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_CALC_07: Penny clipping on balance
    code = apply_replacement(
        canonical_source,
        'acct.acct_curr_bal = Decimal(inp.curr_bal.strip())',
        'acct.acct_curr_bal = Decimal(inp.curr_bal.strip()) - Decimal("0.01")',
        "DEF_CALC_07",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_07", "category": "incorrect_calculation", "operator": "penny_clipping",
        "source_file": "experiments/mutants/candidate_DEF_CALC_07.py",
        "changed_function": "_apply_acct_input", "changed_line": "361",
        "description": "Deducts 1 cent from current balance on update",
        "trigger_condition": "ACTION == 'S' with valid edits and CURR_BAL provided",
        "expected_observable_difference": "ACCT_BAL is $0.01 less than input",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_CALC_08: Flat $500 bonus added to credit limit
    code = apply_replacement(
        canonical_source,
        'acct.acct_credit_limit = Decimal(inp.credit_limit.strip())',
        'acct.acct_credit_limit = Decimal(inp.credit_limit.strip()) + Decimal("500.00")',
        "DEF_CALC_08",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_08", "category": "incorrect_calculation", "operator": "credit_limit_bonus",
        "source_file": "experiments/mutants/candidate_DEF_CALC_08.py",
        "changed_function": "_apply_acct_input", "changed_line": "351",
        "description": "Adds unauthorized $500 bonus to credit limit",
        "trigger_condition": "ACTION == 'S' with valid edits",
        "expected_observable_difference": "CREDIT_LIMIT is $500 greater than input",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_CALC_09: Cash limit overwritten with credit limit
    code = apply_replacement(
        canonical_source,
        'acct.acct_cash_credit_limit = Decimal(inp.cash_credit_limit.strip())',
        'acct.acct_cash_credit_limit = Decimal(inp.credit_limit.strip())',
        "DEF_CALC_09",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_09", "category": "incorrect_calculation", "operator": "variable_misassignment",
        "source_file": "experiments/mutants/candidate_DEF_CALC_09.py",
        "changed_function": "_apply_acct_input", "changed_line": "356",
        "description": "Sets cash credit limit to credit limit instead of cash credit limit input",
        "trigger_condition": "ACTION == 'S' with valid edits and credit != cash credit",
        "expected_observable_difference": "CASH_CREDIT_LIMIT equals CREDIT_LIMIT",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_CALC_10: FICO inflation by 50 points
    code = apply_replacement(
        canonical_source,
        'cust.cust_fico_credit_score = int(inp.fico_score.strip())',
        'cust.cust_fico_credit_score = min(850, int(inp.fico_score.strip()) + 50)',
        "DEF_CALC_10",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_10", "category": "incorrect_calculation", "operator": "fico_score_inflation",
        "source_file": "experiments/mutants/candidate_DEF_CALC_10.py",
        "changed_function": "_apply_cust_input", "changed_line": "400",
        "description": "Inflates customer FICO score by 50 points",
        "trigger_condition": "ACTION == 'S' with valid edits and FICO_SCORE provided",
        "expected_observable_difference": "FICO_SCORE updated with +50 points",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_CALC_11: Edge precision overflow on high credit limits >= 99999.00
    code = apply_replacement(
        canonical_source,
        'acct.acct_credit_limit = Decimal(inp.credit_limit.strip())',
        'acct.acct_credit_limit = (Decimal("99999.00") if Decimal(inp.credit_limit.strip()) >= Decimal("99999.00") else Decimal(inp.credit_limit.strip()))',
        "DEF_CALC_11",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_11", "category": "incorrect_calculation", "operator": "precision_clamp_overflow",
        "source_file": "experiments/mutants/candidate_DEF_CALC_11.py",
        "changed_function": "_apply_acct_input", "changed_line": "351",
        "description": "Clamps credit limit to 99999.00 for extreme high limits (subtle edge defect)",
        "trigger_condition": "ACTION == 'S' and CREDIT_LIMIT >= 99999.00",
        "expected_observable_difference": "CREDIT_LIMIT clamped to 99999.00",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_CALC_12: Zeroing negative balance on update
    code = apply_replacement(
        canonical_source,
        'acct.acct_curr_bal = Decimal(inp.curr_bal.strip())',
        'acct.acct_curr_bal = (Decimal("0.00") if Decimal(inp.curr_bal.strip()) < 0 else Decimal(inp.curr_bal.strip()))',
        "DEF_CALC_12",
    )
    mutant_records.append({
        "case_id": "DEF_CALC_12", "category": "incorrect_calculation", "operator": "negative_balance_squashing",
        "source_file": "experiments/mutants/candidate_DEF_CALC_12.py",
        "changed_function": "_apply_acct_input", "changed_line": "361",
        "description": "Squashes negative balance to $0.00 instead of preserving credit balance",
        "trigger_condition": "ACTION == 'S' with valid edits and CURR_BAL < 0",
        "expected_observable_difference": "Negative balance replaced by 0.00",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # ─────────────────────────────────────────────────────────────────────────
    # Category 2: boundary_condition (12 cases)
    # ─────────────────────────────────────────────────────────────────────────

    # DEF_BOUND_01: Rejection of status 'N' (requires active_status == 'Y')
    code = apply_replacement(
        canonical_source,
        'if status not in ("Y", "N"):',
        'if status not in ("Y",):',
        "DEF_BOUND_01",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_01", "category": "boundary_condition", "operator": "strict_status_boundary",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_01.py",
        "changed_function": "_validate_inputs", "changed_line": "315",
        "description": "Rejects inactive account status 'N', allowing only 'Y'",
        "trigger_condition": "ACTIVE_STATUS == 'N'",
        "expected_observable_difference": "Validation error on valid 'N' status",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_BOUND_02: Credit limit ceiling at $50,000
    code = apply_replacement(
        canonical_source,
        'Decimal(v)',
        'd_val = Decimal(v)\n            if "Credit" in label and d_val > Decimal("50000.00"):\n                errors.append(f"{label} exceeds maximum allowed $50,000")\n                return errors',
        "DEF_BOUND_02",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_02", "category": "boundary_condition", "operator": "credit_ceiling_limit",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_02.py",
        "changed_function": "_validate_inputs", "changed_line": "328",
        "description": "Imposes unauthorized $50,000 upper bound on credit limit",
        "trigger_condition": "CREDIT_LIMIT > 50000.00",
        "expected_observable_difference": "Rejects valid credit limits > 50000",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_BOUND_03: Cash limit strictly greater than $0 (rejects 0.00)
    code = apply_replacement(
        canonical_source,
        'Decimal(v)',
        'd_val = Decimal(v)\n            if "Cash" in label and d_val <= Decimal("0.00"):\n                errors.append("Cash credit limit must be greater than zero")\n                return errors',
        "DEF_BOUND_03",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_03", "category": "boundary_condition", "operator": "cash_credit_zero_floor",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_03.py",
        "changed_function": "_validate_inputs", "changed_line": "328",
        "description": "Rejects valid $0.00 cash credit limit",
        "trigger_condition": "CASH_CREDIT_LIMIT == '0.00'",
        "expected_observable_difference": "Rejects valid 0.00 cash limit",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_BOUND_04: Truncates last names longer than 10 characters
    code = apply_replacement(
        canonical_source,
        '_set("cust_last_name", inp.last_name)',
        '_set("cust_last_name", inp.last_name[:10] if inp.last_name else "")',
        "DEF_BOUND_04",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_04", "category": "boundary_condition", "operator": "string_length_truncation",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_04.py",
        "changed_function": "_apply_cust_input", "changed_line": "385",
        "description": "Truncates last name to 10 characters instead of full buffer",
        "trigger_condition": "len(LAST_NAME) > 10",
        "expected_observable_difference": "LAST_NAME truncated to 10 chars",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_BOUND_05: Account ID lower bound check off-by-one (rejects 100000001)
    code = apply_replacement(
        canonical_source,
        'if acct_id == 0:',
        'if acct_id <= 100000001:',
        "DEF_BOUND_05",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_05", "category": "boundary_condition", "operator": "off_by_one_account_bound",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_05.py",
        "changed_function": "_initial_display", "changed_line": "203",
        "description": "Rejects primary seed account 100000001 with off-by-one check",
        "trigger_condition": "ACCT_ID == '100000001'",
        "expected_observable_difference": "Account 100000001 rejected as invalid",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_BOUND_06: FICO score floor at 350 instead of 300
    code = apply_replacement(
        canonical_source,
        'cust.cust_fico_credit_score = int(inp.fico_score.strip())',
        'f_val = int(inp.fico_score.strip())\n            if f_val < 350:\n                pass\n            else:\n                cust.cust_fico_credit_score = f_val',
        "DEF_BOUND_06",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_06", "category": "boundary_condition", "operator": "fico_score_floor_shift",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_06.py",
        "changed_function": "_apply_cust_input", "changed_line": "400",
        "description": "Ignores FICO scores between 300 and 349",
        "trigger_condition": "300 <= FICO_SCORE < 350",
        "expected_observable_difference": "FICO scores < 350 not updated",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_BOUND_07: FICO score upper bound clamped at 800 instead of 850
    code = apply_replacement(
        canonical_source,
        'cust.cust_fico_credit_score = int(inp.fico_score.strip())',
        'cust.cust_fico_credit_score = min(800, int(inp.fico_score.strip()))',
        "DEF_BOUND_07",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_07", "category": "boundary_condition", "operator": "fico_upper_clamp",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_07.py",
        "changed_function": "_apply_cust_input", "changed_line": "400",
        "description": "Clamps FICO score to 800, rejecting scores up to 850",
        "trigger_condition": "FICO_SCORE > 800",
        "expected_observable_difference": "Scores > 800 recorded as 800",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_BOUND_08: Disallows credit limit < 100.00
    code = apply_replacement(
        canonical_source,
        'Decimal(v)',
        'd_val = Decimal(v)\n            if "Credit" in label and d_val < Decimal("100.00"):\n                errors.append("Credit limit must be at least $100")\n                return errors',
        "DEF_BOUND_08",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_08", "category": "boundary_condition", "operator": "minimum_credit_floor",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_08.py",
        "changed_function": "_validate_inputs", "changed_line": "328",
        "description": "Rejects valid credit limits under $100",
        "trigger_condition": "0 <= CREDIT_LIMIT < 100.00",
        "expected_observable_difference": "Rejects low credit limits < 100",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_BOUND_09: Strict 5-digit zip validation rejecting 9-digit zip+4
    code = apply_replacement(
        canonical_source,
        '_set("cust_addr_zip", inp.addr_zip)',
        'if inp.addr_zip and len(inp.addr_zip.strip()) != 5:\n        pass\n    else:\n        _set("cust_addr_zip", inp.addr_zip)',
        "DEF_BOUND_09",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_09", "category": "boundary_condition", "operator": "zip_length_restriction",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_09.py",
        "changed_function": "_apply_cust_input", "changed_line": "391",
        "description": "Ignores ZIP codes that are not exactly 5 digits",
        "trigger_condition": "len(ADDR_ZIP) != 5",
        "expected_observable_difference": "Non-5-digit zip codes dropped",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_BOUND_10: Account upper bound off-by-one check
    code = apply_replacement(
        canonical_source,
        'if acct is None:',
        'if acct_id >= 999999999:\n        result.error = True\n        result.message = "Account number exceeds maximum"\n        return result\n    if acct is None:',
        "DEF_BOUND_10",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_10", "category": "boundary_condition", "operator": "upper_account_bound_clamp",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_10.py",
        "changed_function": "_initial_display", "changed_line": "211",
        "description": "Prematurely rejects account IDs >= 999999999",
        "trigger_condition": "ACCT_ID == '999999999'",
        "expected_observable_difference": "Account 999999999 rejected with premature error",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_BOUND_11: Disallows negative current balances in validation
    code = apply_replacement(
        canonical_source,
        'if not last:',
        'if inp.curr_bal and Decimal(inp.curr_bal.strip()) < 0:\n        errors.append("Current balance cannot be negative")\n        return errors\n    if not last:',
        "DEF_BOUND_11",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_11", "category": "boundary_condition", "operator": "negative_balance_rejection",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_11.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Rejects valid credit/overpayment balances (< 0)",
        "trigger_condition": "CURR_BAL < 0",
        "expected_observable_difference": "Validation failure on negative balance",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_BOUND_12: Truncates first name to 8 chars
    code = apply_replacement(
        canonical_source,
        '_set("cust_first_name", inp.first_name)',
        '_set("cust_first_name", inp.first_name[:8] if inp.first_name else "")',
        "DEF_BOUND_12",
    )
    mutant_records.append({
        "case_id": "DEF_BOUND_12", "category": "boundary_condition", "operator": "first_name_truncation",
        "source_file": "experiments/mutants/candidate_DEF_BOUND_12.py",
        "changed_function": "_apply_cust_input", "changed_line": "383",
        "description": "Truncates customer first name to 8 characters",
        "trigger_condition": "len(FIRST_NAME) > 8",
        "expected_observable_difference": "FIRST_NAME truncated",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # ─────────────────────────────────────────────────────────────────────────
    # Category 3: altered_business_rule (12 cases)
    # ─────────────────────────────────────────────────────────────────────────

    # DEF_RULE_01: Enforces cash credit limit <= 50% of credit limit
    code = apply_replacement(
        canonical_source,
        'if not last:',
        'try:\n        if Decimal(inp.cash_credit_limit.strip()) > Decimal(inp.credit_limit.strip()) * Decimal("0.50"):\n            errors.append("Cash credit limit cannot exceed 50% of total limit")\n            return errors\n    except Exception:\n        pass\n    if not last:',
        "DEF_RULE_01",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_01", "category": "altered_business_rule", "operator": "cash_limit_ratio_restriction",
        "source_file": "experiments/mutants/candidate_DEF_RULE_01.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Enforces unapproved business rule: cash limit <= 50% of credit limit",
        "trigger_condition": "CASH_CREDIT_LIMIT > CREDIT_LIMIT * 0.50",
        "expected_observable_difference": "Validation error on valid high cash limit",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_RULE_02: Requires first name cannot be empty
    code = apply_replacement(
        canonical_source,
        'if not last:',
        'if not inp.first_name or not inp.first_name.strip():\n        errors.append("First name is mandatory")\n        return errors\n    if not last:',
        "DEF_RULE_02",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_02", "category": "altered_business_rule", "operator": "mandatory_first_name_rule",
        "source_file": "experiments/mutants/candidate_DEF_RULE_02.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Enforces unauthorized mandatory first name rule",
        "trigger_condition": "FIRST_NAME == ''",
        "expected_observable_difference": "Validation error when first name is omitted",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_RULE_03: Requires FICO >= 700 for credit limit > 15000
    code = apply_replacement(
        canonical_source,
        'if not last:',
        'try:\n        if Decimal(inp.credit_limit.strip()) > Decimal("15000.00") and int(inp.fico_score.strip()) < 700:\n            errors.append("High credit limit requires FICO >= 700")\n            return errors\n    except Exception:\n        pass\n    if not last:',
        "DEF_RULE_03",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_03", "category": "altered_business_rule", "operator": "fico_credit_ratio_rule",
        "source_file": "experiments/mutants/candidate_DEF_RULE_03.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Enforces strict FICO requirement for high credit limits",
        "trigger_condition": "CREDIT_LIMIT > 15000.00 and FICO_SCORE < 700",
        "expected_observable_difference": "Validation error on high limit with sub-700 FICO",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_RULE_04: Rejects status change to 'N' if current balance > 0
    code = apply_replacement(
        canonical_source,
        'if not last:',
        'try:\n        if inp.active_status.strip().upper() == "N" and Decimal(inp.curr_bal.strip()) > 0:\n            errors.append("Cannot deactivate account with outstanding balance")\n            return errors\n    except Exception:\n        pass\n    if not last:',
        "DEF_RULE_04",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_04", "category": "altered_business_rule", "operator": "balance_blocking_deactivation",
        "source_file": "experiments/mutants/candidate_DEF_RULE_04.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Blocks deactivating account when balance > 0",
        "trigger_condition": "ACTIVE_STATUS == 'N' and CURR_BAL > 0",
        "expected_observable_difference": "Deactivation rejected with balance error",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_RULE_05: Requires cash credit limit cannot exceed $5,000
    code = apply_replacement(
        canonical_source,
        'if not last:',
        'try:\n        if Decimal(inp.cash_credit_limit.strip()) > Decimal("5000.00"):\n            errors.append("Cash credit limit capped at $5,000")\n            return errors\n    except Exception:\n        pass\n    if not last:',
        "DEF_RULE_05",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_05", "category": "altered_business_rule", "operator": "flat_cash_limit_cap",
        "source_file": "experiments/mutants/candidate_DEF_RULE_05.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Imposes hard $5,000 ceiling on cash credit limit",
        "trigger_condition": "CASH_CREDIT_LIMIT > 5000.00",
        "expected_observable_difference": "Rejects cash limit > 5000",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_RULE_06: Requires ZIP code to start with '1' or '9'
    code = apply_replacement(
        canonical_source,
        'if not last:',
        'if inp.addr_zip and not (inp.addr_zip.strip().startswith("1") or inp.addr_zip.strip().startswith("9")):\n        errors.append("Unsupported service area zip code")\n        return errors\n    if not last:',
        "DEF_RULE_06",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_06", "category": "altered_business_rule", "operator": "service_area_zip_restriction",
        "source_file": "experiments/mutants/candidate_DEF_RULE_06.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Restricts valid customer addresses to select zip code regions",
        "trigger_condition": "ADDR_ZIP does not start with 1 or 9",
        "expected_observable_difference": "Rejects valid addresses outside regions 1 and 9",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_RULE_07: Requires credit limit to be multiple of $1,000
    code = apply_replacement(
        canonical_source,
        'if not last:',
        'try:\n        if Decimal(inp.credit_limit.strip()) % Decimal("1000.00") != 0:\n            errors.append("Credit limit must be an increment of $1,000")\n            return errors\n    except Exception:\n        pass\n    if not last:',
        "DEF_RULE_07",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_07", "category": "altered_business_rule", "operator": "credit_increment_rule",
        "source_file": "experiments/mutants/candidate_DEF_RULE_07.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Requires credit limit to be exact multiple of 1000",
        "trigger_condition": "CREDIT_LIMIT not multiple of 1000",
        "expected_observable_difference": "Rejects arbitrary credit limits",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_RULE_08: Auto-converts active status to 'N' if FICO < 350
    code = apply_replacement(
        canonical_source,
        'acct.acct_active_status = inp.active_status.strip().upper()[0]',
        'if inp.fico_score and int(inp.fico_score.strip()) < 350:\n            acct.acct_active_status = "N"\n        else:\n            acct.acct_active_status = inp.active_status.strip().upper()[0]',
        "DEF_RULE_08",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_08", "category": "altered_business_rule", "operator": "auto_status_revocation",
        "source_file": "experiments/mutants/candidate_DEF_RULE_08.py",
        "changed_function": "_apply_acct_input", "changed_line": "348",
        "description": "Silently revokes active status to 'N' if FICO score < 350",
        "trigger_condition": "FICO_SCORE < 350 and ACTIVE_STATUS == 'Y'",
        "expected_observable_difference": "ACTIVE_STATUS forced to 'N'",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_RULE_09: Restricts maximum credit limit to $25,000
    code = apply_replacement(
        canonical_source,
        'if not last:',
        'try:\n        if Decimal(inp.credit_limit.strip()) > Decimal("25000.00"):\n            errors.append("Credit limit cannot exceed tier-1 maximum of $25,000")\n            return errors\n    except Exception:\n        pass\n    if not last:',
        "DEF_RULE_09",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_09", "category": "altered_business_rule", "operator": "tier_one_credit_cap",
        "source_file": "experiments/mutants/candidate_DEF_RULE_09.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Caps maximum credit limit to $25,000",
        "trigger_condition": "CREDIT_LIMIT > 25000.00",
        "expected_observable_difference": "Rejects valid credit limits > 25000",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_RULE_10: Requires last name length >= 2
    code = apply_replacement(
        canonical_source,
        'if not last:',
        'if len(last) < 2:\n        errors.append("Last name must be at least 2 characters")\n        return errors\n    if not last:',
        "DEF_RULE_10",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_10", "category": "altered_business_rule", "operator": "minimum_name_length_rule",
        "source_file": "experiments/mutants/candidate_DEF_RULE_10.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Requires last name to be at least 2 characters long",
        "trigger_condition": "len(LAST_NAME) == 1",
        "expected_observable_difference": "Rejects 1-letter valid last names (e.g., 'A')",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_RULE_11: Requires cash credit limit to be > $100
    code = apply_replacement(
        canonical_source,
        'if not last:',
        'try:\n        if Decimal(inp.cash_credit_limit.strip()) < Decimal("100.00"):\n            errors.append("Cash credit limit must be at least $100")\n            return errors\n    except Exception:\n        pass\n    if not last:',
        "DEF_RULE_11",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_11", "category": "altered_business_rule", "operator": "minimum_cash_limit_rule",
        "source_file": "experiments/mutants/candidate_DEF_RULE_11.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Requires cash limit to be at least $100",
        "trigger_condition": "0 <= CASH_CREDIT_LIMIT < 100.00",
        "expected_observable_difference": "Rejects cash limits < 100",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_RULE_12: Rejects accounts not matching seed accounts
    code = apply_replacement(
        canonical_source,
        'acct = acct_repo.find(acct_id)',
        'if acct_id not in (100000001, 100000002):\n        result.error = True\n        result.message = "Account locked by administration policy"\n        return result\n    acct = acct_repo.find(acct_id)',
        "DEF_RULE_12",
    )
    mutant_records.append({
        "case_id": "DEF_RULE_12", "category": "altered_business_rule", "operator": "administrative_account_lockout",
        "source_file": "experiments/mutants/candidate_DEF_RULE_12.py",
        "changed_function": "_initial_display", "changed_line": "211",
        "description": "Rejects access to account 100000003 with administrative policy error",
        "trigger_condition": "ACCT_ID == '100000003'",
        "expected_observable_difference": "Account 100000003 denied access",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # ─────────────────────────────────────────────────────────────────────────
    # Category 4: missing_update (12 cases)
    # ─────────────────────────────────────────────────────────────────────────

    # DEF_UPDATE_01: Omits active_status update
    code = apply_replacement(
        canonical_source,
        'acct.acct_active_status = inp.active_status.strip().upper()[0]',
        'pass  # Missing active_status update',
        "DEF_UPDATE_01",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_01", "category": "missing_update", "operator": "omit_status_update",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_01.py",
        "changed_function": "_apply_acct_input", "changed_line": "348",
        "description": "Omits writing updated active status into account record",
        "trigger_condition": "ACTIVE_STATUS changed from current state",
        "expected_observable_difference": "ACCT_STATUS remains unchanged",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_UPDATE_02: Omits credit_limit update
    code = apply_replacement(
        canonical_source,
        'acct.acct_credit_limit = Decimal(inp.credit_limit.strip())',
        'pass  # Missing credit_limit update',
        "DEF_UPDATE_02",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_02", "category": "missing_update", "operator": "omit_credit_limit_update",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_02.py",
        "changed_function": "_apply_acct_input", "changed_line": "351",
        "description": "Omits writing updated credit limit into account record",
        "trigger_condition": "CREDIT_LIMIT changed from current state",
        "expected_observable_difference": "CREDIT_LIMIT remains unchanged",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_UPDATE_03: Omits cash_credit_limit update
    code = apply_replacement(
        canonical_source,
        'acct.acct_cash_credit_limit = Decimal(inp.cash_credit_limit.strip())',
        'pass  # Missing cash_credit_limit update',
        "DEF_UPDATE_03",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_03", "category": "missing_update", "operator": "omit_cash_limit_update",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_03.py",
        "changed_function": "_apply_acct_input", "changed_line": "356",
        "description": "Omits writing updated cash credit limit into account record",
        "trigger_condition": "CASH_CREDIT_LIMIT changed from current state",
        "expected_observable_difference": "CASH_CREDIT_LIMIT remains unchanged",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_UPDATE_04: Omits customer last_name update
    code = apply_replacement(
        canonical_source,
        '_set("cust_last_name", inp.last_name)',
        'pass  # Missing last_name update',
        "DEF_UPDATE_04",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_04", "category": "missing_update", "operator": "omit_last_name_update",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_04.py",
        "changed_function": "_apply_cust_input", "changed_line": "385",
        "description": "Omits writing updated last name into customer record",
        "trigger_condition": "LAST_NAME changed from current state",
        "expected_observable_difference": "LAST_NAME remains unchanged",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_UPDATE_05: Omits customer first_name update
    code = apply_replacement(
        canonical_source,
        '_set("cust_first_name", inp.first_name)',
        'pass  # Missing first_name update',
        "DEF_UPDATE_05",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_05", "category": "missing_update", "operator": "omit_first_name_update",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_05.py",
        "changed_function": "_apply_cust_input", "changed_line": "383",
        "description": "Omits writing updated first name into customer record",
        "trigger_condition": "FIRST_NAME changed from current state",
        "expected_observable_difference": "FIRST_NAME remains unchanged",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_UPDATE_06: Omits customer fico_score update
    code = apply_replacement(
        canonical_source,
        'cust.cust_fico_credit_score = int(inp.fico_score.strip())',
        'pass  # Missing fico_score update',
        "DEF_UPDATE_06",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_06", "category": "missing_update", "operator": "omit_fico_update",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_06.py",
        "changed_function": "_apply_cust_input", "changed_line": "400",
        "description": "Omits writing updated FICO score into customer record",
        "trigger_condition": "FICO_SCORE changed from current state",
        "expected_observable_difference": "FICO_SCORE remains unchanged",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_UPDATE_07: Omits customer addr_zip update
    code = apply_replacement(
        canonical_source,
        '_set("cust_addr_zip", inp.addr_zip)',
        'pass  # Missing addr_zip update',
        "DEF_UPDATE_07",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_07", "category": "missing_update", "operator": "omit_zip_update",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_07.py",
        "changed_function": "_apply_cust_input", "changed_line": "391",
        "description": "Omits writing updated ZIP code into customer record",
        "trigger_condition": "ADDR_ZIP changed from current state",
        "expected_observable_difference": "ADDR_ZIP remains unchanged",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_UPDATE_08: Omits curr_bal update
    code = apply_replacement(
        canonical_source,
        'acct.acct_curr_bal = Decimal(inp.curr_bal.strip())',
        'pass  # Missing curr_bal update',
        "DEF_UPDATE_08",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_08", "category": "missing_update", "operator": "omit_balance_update",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_08.py",
        "changed_function": "_apply_acct_input", "changed_line": "361",
        "description": "Omits writing updated current balance into account record",
        "trigger_condition": "CURR_BAL changed from current state",
        "expected_observable_difference": "ACCT_BAL remains unchanged",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_UPDATE_09: Omits writing customer record to repository on commit
    code = apply_replacement(
        canonical_source,
        'if not cust_repo.rewrite(new_cust):',
        'if False:  # Omitted rewrite(new_cust)\n        pass\n    elif False:',
        "DEF_UPDATE_09",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_09", "category": "missing_update", "operator": "omit_customer_rewrite",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_09.py",
        "changed_function": "_commit_changes", "changed_line": "289",
        "description": "Omits invoking cust_repo.rewrite on commit phase",
        "trigger_condition": "ACTION == 'N' and EIBAID == 'PF5'",
        "expected_observable_difference": "Customer database updates silently dropped on commit",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_UPDATE_10: Omits writing account record to repository on commit
    code = apply_replacement(
        canonical_source,
        'if not acct_repo.rewrite(new_acct):',
        'if False:  # Omitted rewrite(new_acct)\n        pass\n    elif False:',
        "DEF_UPDATE_10",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_10", "category": "missing_update", "operator": "omit_account_rewrite",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_10.py",
        "changed_function": "_commit_changes", "changed_line": "280",
        "description": "Omits invoking acct_repo.rewrite on commit phase",
        "trigger_condition": "ACTION == 'N' and EIBAID == 'PF5'",
        "expected_observable_difference": "Account database updates silently dropped on commit",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_UPDATE_11: Omits updating expiration date
    code = apply_replacement(
        canonical_source,
        'acct.acct_expiration_date = inp.expiry_date.strip()',
        'pass  # Missing expiry_date update',
        "DEF_UPDATE_11",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_11", "category": "missing_update", "operator": "omit_expiry_date_update",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_11.py",
        "changed_function": "_apply_acct_input", "changed_line": "367",
        "description": "Omits writing updated expiration date into account record",
        "trigger_condition": "expiry_date provided in input",
        "expected_observable_difference": "Expiration date not updated",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_UPDATE_12: Omits updating group ID
    code = apply_replacement(
        canonical_source,
        'acct.acct_group_id = inp.group_id.strip()',
        'pass  # Missing group_id update',
        "DEF_UPDATE_12",
    )
    mutant_records.append({
        "case_id": "DEF_UPDATE_12", "category": "missing_update", "operator": "omit_group_id_update",
        "source_file": "experiments/mutants/candidate_DEF_UPDATE_12.py",
        "changed_function": "_apply_acct_input", "changed_line": "371",
        "description": "Omits writing updated group ID into account record",
        "trigger_condition": "group_id provided in input",
        "expected_observable_difference": "Group ID not updated",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # ─────────────────────────────────────────────────────────────────────────
    # Category 5: incorrect_transaction_handling (12 cases)
    # ─────────────────────────────────────────────────────────────────────────

    # DEF_TX_01: Corrupts PF3 return destination
    code = apply_replacement(
        canonical_source,
        'back = commarea.cdemo_from_program or "COMEN01C"',
        'back = "COSGN00C"  # Incorrectly routes all PF3 returns to signon',
        "DEF_TX_01",
    )
    mutant_records.append({
        "case_id": "DEF_TX_01", "category": "incorrect_transaction_handling", "operator": "corrupt_pf3_navigation",
        "source_file": "experiments/mutants/candidate_DEF_TX_01.py",
        "changed_function": "process_account_update", "changed_line": "157",
        "description": "Routes PF3 exit to COSGN00C instead of caller program",
        "trigger_condition": "EIBAID == 'PF3' and from_program != 'COSGN00C'",
        "expected_observable_difference": "XCTL_PROGRAM routes to COSGN00C instead of COMEN01C",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_TX_02: Corrupts PF12 card list navigation destination
    code = apply_replacement(
        canonical_source,
        'result.xctl_program = "COCRDLIC"',
        'result.xctl_program = "COMEN01C"  # Incorrectly routes PF12 to menu',
        "DEF_TX_02",
    )
    mutant_records.append({
        "case_id": "DEF_TX_02", "category": "incorrect_transaction_handling", "operator": "corrupt_pf12_navigation",
        "source_file": "experiments/mutants/candidate_DEF_TX_02.py",
        "changed_function": "process_account_update", "changed_line": "173",
        "description": "Routes PF12 exit to COMEN01C instead of COCRDLIC",
        "trigger_condition": "EIBAID == 'PF12' and ACTION in ('N', 'E')",
        "expected_observable_difference": "XCTL_PROGRAM routes to COMEN01C instead of COCRDLIC",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_TX_03: Does not advance action flag to 'C' on commit
    code = apply_replacement(
        canonical_source,
        'result.action = "C"',
        'result.action = "N"  # Fails to transition state machine to C',
        "DEF_TX_03",
    )
    mutant_records.append({
        "case_id": "DEF_TX_03", "category": "incorrect_transaction_handling", "operator": "omit_action_state_transition",
        "source_file": "experiments/mutants/candidate_DEF_TX_03.py",
        "changed_function": "_commit_changes", "changed_line": "298",
        "description": "Leaves action state at 'N' after committing database updates",
        "trigger_condition": "ACTION == 'N' and EIBAID == 'PF5'",
        "expected_observable_difference": "ACTION remains 'N' instead of 'C'",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_TX_04: Does not set action flag to 'S' on initial lookup
    code = apply_replacement(
        canonical_source,
        'result.action = "S"',
        'result.action = ""  # Fails to advance to S on lookup',
        "DEF_TX_04",
    )
    mutant_records.append({
        "case_id": "DEF_TX_04", "category": "incorrect_transaction_handling", "operator": "omit_lookup_state_transition",
        "source_file": "experiments/mutants/candidate_DEF_TX_04.py",
        "changed_function": "_initial_display", "changed_line": "238",
        "description": "Leaves action state empty after successful account lookup",
        "trigger_condition": "ACTION == '' and valid ACCT_ID lookup",
        "expected_observable_difference": "ACTION remains empty instead of advancing to 'S'",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_TX_05: First entry does not set return_to_prev = True
    code = apply_replacement(
        canonical_source,
        'result.return_to_prev = True\n        result.xctl_program = "COSGN00C"',
        'result.return_to_prev = False\n        result.xctl_program = "COSGN00C"',
        "DEF_TX_05",
    )
    mutant_records.append({
        "case_id": "DEF_TX_05", "category": "incorrect_transaction_handling", "operator": "corrupt_return_flag",
        "source_file": "experiments/mutants/candidate_DEF_TX_05.py",
        "changed_function": "process_account_update", "changed_line": "150",
        "description": "Fails to set return_to_prev flag on unauthenticated first entry",
        "trigger_condition": "EIBCALEN == 0",
        "expected_observable_difference": "RETURN_TO_PREV is 'N' instead of 'Y'",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_TX_06: Validation error sets action to 'S' instead of 'E'
    code = apply_replacement(
        canonical_source,
        'result.action = "E"',
        'result.action = "S"  # Mask error state in state machine',
        "DEF_TX_06",
    )
    mutant_records.append({
        "case_id": "DEF_TX_06", "category": "incorrect_transaction_handling", "operator": "mask_error_state",
        "source_file": "experiments/mutants/candidate_DEF_TX_06.py",
        "changed_function": "_validate_and_preview", "changed_line": "252",
        "description": "Sets action to 'S' instead of 'E' upon input validation failure",
        "trigger_condition": "ACTION == 'S' with invalid input edits",
        "expected_observable_difference": "ACTION is 'S' instead of 'E' upon validation error",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_TX_07: Commits on ENTER key instead of requiring PF5
    code = apply_replacement(
        canonical_source,
        'if eibaid in (DFHPF5, "PF5") and current_action == "N":',
        'if current_action == "N":  # Commits unconditionally on any key including ENTER',
        "DEF_TX_07",
    )
    mutant_records.append({
        "case_id": "DEF_TX_07", "category": "incorrect_transaction_handling", "operator": "unconfirmed_commit_on_enter",
        "source_file": "experiments/mutants/candidate_DEF_TX_07.py",
        "changed_function": "process_account_update", "changed_line": "170",
        "description": "Commits database changes on ENTER without waiting for PF5 confirmation",
        "trigger_condition": "ACTION == 'N' and EIBAID == 'ENTER'",
        "expected_observable_difference": "Commits prematurely without PF5 confirmation",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_TX_08: Masks error flag on account lookup failure
    code = apply_replacement(
        canonical_source,
        'result.error = True\n        result.message = "Did not find this account in account master file"',
        'result.error = False  # Mask error flag\n        result.message = "Did not find this account in account master file"',
        "DEF_TX_08",
    )
    mutant_records.append({
        "case_id": "DEF_TX_08", "category": "incorrect_transaction_handling", "operator": "mask_lookup_error_flag",
        "source_file": "experiments/mutants/candidate_DEF_TX_08.py",
        "changed_function": "_initial_display", "changed_line": "213",
        "description": "Sets error=False when account is not found in master file",
        "trigger_condition": "ACTION == '' with non-existent ACCT_ID",
        "expected_observable_difference": "ERROR flag is 'N' despite account not found",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_TX_09: Resets commarea context on navigation
    code = apply_replacement(
        canonical_source,
        'result.commarea = commarea\n\n    if eibaid in (DFHPF3, "PF3"):',
        'result.commarea = None  # Corrupts commarea preservation\n\n    if eibaid in (DFHPF3, "PF3"):',
        "DEF_TX_09",
    )
    mutant_records.append({
        "case_id": "DEF_TX_09", "category": "incorrect_transaction_handling", "operator": "drop_commarea_context",
        "source_file": "experiments/mutants/candidate_DEF_TX_09.py",
        "changed_function": "process_account_update", "changed_line": "154",
        "description": "Drops CICS commarea context during transaction processing",
        "trigger_condition": "Any valid transaction execution",
        "expected_observable_difference": "Commarea context lost across transactions",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_TX_10: Silently empties success message on commit
    code = apply_replacement(
        canonical_source,
        'result.message = "Changes committed to database"',
        'result.message = ""  # Drops user confirmation message',
        "DEF_TX_10",
    )
    mutant_records.append({
        "case_id": "DEF_TX_10", "category": "incorrect_transaction_handling", "operator": "suppress_success_message",
        "source_file": "experiments/mutants/candidate_DEF_TX_10.py",
        "changed_function": "_commit_changes", "changed_line": "302",
        "description": "Omits user confirmation message upon successful commit",
        "trigger_condition": "ACTION == 'N' and EIBAID == 'PF5'",
        "expected_observable_difference": "MESSAGE is empty upon successful commit",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_TX_11: Routes PF12 to signon screen instead of card list
    code = apply_replacement(
        canonical_source,
        'result.xctl_program = "COCRDLIC"',
        'result.xctl_program = "COSGN00C"  # Diverts PF12 to signon',
        "DEF_TX_11",
    )
    mutant_records.append({
        "case_id": "DEF_TX_11", "category": "incorrect_transaction_handling", "operator": "divert_pf12_navigation",
        "source_file": "experiments/mutants/candidate_DEF_TX_11.py",
        "changed_function": "process_account_update", "changed_line": "173",
        "description": "Diverts PF12 card list navigation to signon screen",
        "trigger_condition": "EIBAID == 'PF12' and ACTION in ('N', 'E')",
        "expected_observable_difference": "XCTL_PROGRAM routes to COSGN00C instead of COCRDLIC",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # DEF_TX_12: Re-triggers first-entry logic on EIBCALEN == 1
    code = apply_replacement(
        canonical_source,
        'if eibcalen == 0:',
        'if eibcalen <= 1:  # Treats calen=1 as unauthenticated entry',
        "DEF_TX_12",
    )
    mutant_records.append({
        "case_id": "DEF_TX_12", "category": "incorrect_transaction_handling", "operator": "calen_boundary_corruption",
        "source_file": "experiments/mutants/candidate_DEF_TX_12.py",
        "changed_function": "process_account_update", "changed_line": "149",
        "description": "Treats EIBCALEN == 1 as unauthenticated first entry (subtle edge defect)",
        "trigger_condition": "EIBCALEN == 1",
        "expected_observable_difference": "Premature redirect to COSGN00C when CALEN is 1",
        "ground_truth": "DEFECTIVE", "source_code": code,
    })

    # ─────────────────────────────────────────────────────────────────────────
    # Category 6: equivalent_controls (15 cases)
    # Genuine source-level refactorings with identical observable semantics
    # ─────────────────────────────────────────────────────────────────────────

    # EQUIV_01: De Morgan condition rewrite on active_status check
    code = apply_replacement(
        canonical_source,
        'if status not in ("Y", "N"):',
        'if status != "Y" and status != "N":  # Equivalent De Morgan refactoring',
        "EQUIV_01",
    )
    mutant_records.append({
        "case_id": "EQUIV_01", "category": "equivalent_control", "operator": "de_morgan_condition_rewrite",
        "source_file": "experiments/mutants/candidate_EQUIV_01.py",
        "changed_function": "_validate_inputs", "changed_line": "315",
        "description": "Refactored status check to explicit conjunction: status != 'Y' and status != 'N'",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_02: Commutative boolean expression on PF3 check
    code = apply_replacement(
        canonical_source,
        'if eibaid in (DFHPF3, "PF3"):',
        'if eibaid == "PF3" or eibaid == DFHPF3:  # Equivalent commutative check',
        "EQUIV_02",
    )
    mutant_records.append({
        "case_id": "EQUIV_02", "category": "equivalent_control", "operator": "commutative_or_refactoring",
        "source_file": "experiments/mutants/candidate_EQUIV_02.py",
        "changed_function": "process_account_update", "changed_line": "156",
        "description": "Replaced membership test with commutative disjunction: eibaid == 'PF3' or eibaid == DFHPF3",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_03: Reordered independent loop elements for credit limit checking
    code = apply_replacement(
        canonical_source,
        'for label, val in [\n        ("Credit Limit", inp.credit_limit),\n        ("Cash Credit Limit", inp.cash_credit_limit),\n    ]:',
        'for label, val in [\n        ("Cash Credit Limit", inp.cash_credit_limit),\n        ("Credit Limit", inp.credit_limit),\n    ]:  # Reordered independent checks',
        "EQUIV_03",
    )
    mutant_records.append({
        "case_id": "EQUIV_03", "category": "equivalent_control", "operator": "independent_validation_reordering",
        "source_file": "experiments/mutants/candidate_EQUIV_03.py",
        "changed_function": "_validate_inputs", "changed_line": "319",
        "description": "Reordered independent credit limit and cash credit limit validation checks",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_04: Extracted decimal parser helper function
    helper = """def _parse_decimal_safe(val: str) -> Decimal:
    return Decimal(val.strip())


"""
    code = apply_replacement(
        canonical_source,
        'def _validate_inputs(inp: AccountUpdateInput) -> list[str]:',
        helper + 'def _validate_inputs(inp: AccountUpdateInput) -> list[str]:',
        "EQUIV_04_helper",
    )
    code = apply_replacement(
        code,
        'Decimal(v)',
        '_parse_decimal_safe(v)',
        "EQUIV_04",
    )
    mutant_records.append({
        "case_id": "EQUIV_04", "category": "equivalent_control", "operator": "extracted_helper_method",
        "source_file": "experiments/mutants/candidate_EQUIV_04.py",
        "changed_function": "_validate_inputs", "changed_line": "328",
        "description": "Extracted Decimal string parsing logic into private safe helper function",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_05: Dictionary get method with default for repository lookup
    code = apply_replacement(
        canonical_source,
        'return self._accounts.get(acct_id)',
        'return self._accounts[acct_id] if acct_id in self._accounts else None  # Equivalent get() logic',
        "EQUIV_05",
    )
    mutant_records.append({
        "case_id": "EQUIV_05", "category": "equivalent_control", "operator": "explicit_membership_lookup",
        "source_file": "experiments/mutants/candidate_EQUIV_05.py",
        "changed_function": "AccountRepository.find", "changed_line": "101",
        "description": "Replaced dict.get() with explicit key membership check before indexing",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_06: Regex digit matching equivalent to isdigit()
    code = apply_replacement(
        canonical_source,
        'if not acct_id_str.strip().isdigit():',
        'if not re.fullmatch(r"[0-9]+", acct_id_str.strip()):  # Equivalent regex digit validation',
        "EQUIV_06",
    )
    mutant_records.append({
        "case_id": "EQUIV_06", "category": "equivalent_control", "operator": "regex_digit_equivalence",
        "source_file": "experiments/mutants/candidate_EQUIV_06.py",
        "changed_function": "_initial_display", "changed_line": "194",
        "description": "Substituted isdigit() with compiled fullmatch regex equivalent",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_07: Explicit ternary null check on ScreenHeader errmsg assignment
    code = apply_replacement(
        canonical_source,
        'result.screen.errmsg = result.message',
        'if result.screen is not None:\n            result.screen.errmsg = result.message  # Guarded null check',
        "EQUIV_07",
    )
    mutant_records.append({
        "case_id": "EQUIV_07", "category": "equivalent_control", "operator": "guarded_null_check",
        "source_file": "experiments/mutants/candidate_EQUIV_07.py",
        "changed_function": "_initial_display", "changed_line": "198",
        "description": "Added defensive null check on ScreenHeader errmsg assignment",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_08: Customer record assignment using explicit dictionary dispatch
    code = apply_replacement(
        canonical_source,
        'def _set(attr, val):\n        if val and val.strip():\n            setattr(cust, attr, val.strip())',
        'def _set(attr, val):\n        v_clean = val.strip() if (val is not None and isinstance(val, str)) else ""\n        if len(v_clean) > 0:\n            setattr(cust, attr, v_clean)',
        "EQUIV_08",
    )
    mutant_records.append({
        "case_id": "EQUIV_08", "category": "equivalent_control", "operator": "attribute_setter_refactoring",
        "source_file": "experiments/mutants/candidate_EQUIV_08.py",
        "changed_function": "_apply_cust_input", "changed_line": "379",
        "description": "Refactored customer attribute setter closure with explicit length guard",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_09: Commutative error check in account repository rewrite
    code = apply_replacement(
        canonical_source,
        'if acct.acct_id not in self._accounts:',
        'if not (acct.acct_id in self._accounts):  # Commutative boolean guard',
        "EQUIV_09",
    )
    mutant_records.append({
        "case_id": "EQUIV_09", "category": "equivalent_control", "operator": "commutative_error_guard",
        "source_file": "experiments/mutants/candidate_EQUIV_09.py",
        "changed_function": "AccountRepository.rewrite", "changed_line": "104",
        "description": "Rewrote 'acct_id not in accounts' as 'not (acct_id in accounts)'",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_10: Explicit string casting before Decimal parsing in _apply_acct_input
    code = apply_replacement(
        canonical_source,
        'acct.acct_credit_limit = Decimal(inp.credit_limit.strip())',
        'acct.acct_credit_limit = Decimal(str(inp.credit_limit).strip())  # Explicit str cast',
        "EQUIV_10",
    )
    mutant_records.append({
        "case_id": "EQUIV_10", "category": "equivalent_control", "operator": "explicit_str_casting",
        "source_file": "experiments/mutants/candidate_EQUIV_10.py",
        "changed_function": "_apply_acct_input", "changed_line": "351",
        "description": "Explicitly wraps input in str() prior to Decimal construction",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_11: Pre-stripped input field caching
    code = apply_replacement(
        canonical_source,
        'last = inp.last_name.strip() if inp.last_name else ""',
        'raw_last = inp.last_name or ""\n    last = raw_last.strip()  # Pre-stripped string caching',
        "EQUIV_11",
    )
    mutant_records.append({
        "case_id": "EQUIV_11", "category": "equivalent_control", "operator": "pre_stripped_string_caching",
        "source_file": "experiments/mutants/candidate_EQUIV_11.py",
        "changed_function": "_validate_inputs", "changed_line": "333",
        "description": "Refactored last_name strip logic to two-step assignment",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_12: List generator accumulation for errors
    code = apply_replacement(
        canonical_source,
        'errors: list[str] = []',
        'errors: list[str] = list()  # Explicit list constructor call',
        "EQUIV_12",
    )
    mutant_records.append({
        "case_id": "EQUIV_12", "category": "equivalent_control", "operator": "explicit_constructor_call",
        "source_file": "experiments/mutants/candidate_EQUIV_12.py",
        "changed_function": "_validate_inputs", "changed_line": "312",
        "description": "Replaced empty literal [] with explicit list() constructor call",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_13: Dict comprehension seed data copy
    code = apply_replacement(
        canonical_source,
        'class AccountRepository:\n    def __init__(self, accounts: dict[int, AccountRecord]):\n        self._accounts = accounts',
        'class AccountRepository:\n    def __init__(self, accounts: dict[int, AccountRecord]):\n        self._accounts = {k: v for k, v in accounts.items()}  # Dict comprehension clone',
        "EQUIV_13",
    )
    mutant_records.append({
        "case_id": "EQUIV_13", "category": "equivalent_control", "operator": "dict_comprehension_cloning",
        "source_file": "experiments/mutants/candidate_EQUIV_13.py",
        "changed_function": "AccountRepository.__init__", "changed_line": "98",
        "description": "Cloned repository dictionary using comprehension instead of direct reference",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_14: Action routing condition refactoring
    code = apply_replacement(
        canonical_source,
        'if current_action == "S":',
        'if current_action in ("S",):  # Tuple membership check',
        "EQUIV_14",
    )
    mutant_records.append({
        "case_id": "EQUIV_14", "category": "equivalent_control", "operator": "tuple_membership_refactoring",
        "source_file": "experiments/mutants/candidate_EQUIV_14.py",
        "changed_function": "process_account_update", "changed_line": "166",
        "description": "Replaced equality check '== S' with single-element tuple membership check",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    # EQUIV_15: Explicit boolean evaluation on result.error in _commit_changes
    code = apply_replacement(
        canonical_source,
        'result.success = True',
        'result.success = bool(1)  # Explicit boolean coercion',
        "EQUIV_15",
    )
    mutant_records.append({
        "case_id": "EQUIV_15", "category": "equivalent_control", "operator": "explicit_boolean_coercion",
        "source_file": "experiments/mutants/candidate_EQUIV_15.py",
        "changed_function": "_commit_changes", "changed_line": "299",
        "description": "Replaced literal True with bool(1) constructor coercion",
        "trigger_condition": "Semantics-preserving across all inputs",
        "expected_observable_difference": "Zero observable divergence",
        "ground_truth": "EQUIVALENT", "source_code": code,
    })

    assert len(mutant_records) == 76, f"Expected 76 cases, generated {len(mutant_records)}"

    manifest_entries = []
    print(f"Synthesizing and compiling {len(mutant_records)} genuine source mutant files...")

    for rec in mutant_records:
        target_path = BASE_DIR / rec["source_file"]
        code_text = rec["source_code"]
        target_path.write_text(code_text, encoding="utf-8")

        # Compile validation
        py_compile.compile(str(target_path), doraise=True)

        mutated_hash = sha256_str(code_text)
        manifest_entries.append({
            "case_id": rec["case_id"],
            "category": rec["category"],
            "operator": rec["operator"],
            "source_file": rec["source_file"],
            "changed_function": rec["changed_function"],
            "changed_line": rec["changed_line"],
            "description": rec["description"],
            "trigger_condition": rec["trigger_condition"],
            "expected_observable_difference": rec["expected_observable_difference"],
            "ground_truth": rec["ground_truth"],
            "canonical_source_hash": canonical_hash,
            "mutated_source_hash": mutated_hash,
            "is_semantically_equivalent": rec["ground_truth"] == "EQUIVALENT",
            "compilation_status": "SUCCESS",
        })

    manifest_path = BASE_DIR / "results" / "source_mutants_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "total_mutants": len(manifest_entries),
            "canonical_source": "data/staged_sources/modern/coactupc.py",
            "canonical_sha256": canonical_hash,
            "cases": manifest_entries,
        }, f, indent=2)

    print(f"Successfully generated and compiled 76 mutants.")
    print(f"Manifest saved to: {manifest_path}")
    return manifest_entries


if __name__ == "__main__":
    generate_all_mutants()
