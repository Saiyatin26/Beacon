"""BEACON Independent Benchmark: Source Mutant and Control Builder for Masquerade CBTRN02C.

Synthesizes 30 genuine standalone candidate source variants in `experiments/masquerade_mutants/`:
- 24 Defective candidates across 5 defect categories (CALC, VAL, STATE, TX, FLOW)
- 6 Behavior-preserving equivalent controls (De Morgan, helper extraction, dict get, etc.)

Measures empirical trigger rates over 1,000 independent random transactions to establish
sealed ground-truth labels.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import sys
from typing import Any

# Ensure path
sys.path.insert(0, ".")
MASQUERADE_PATH = Path("c:/Users/Navaneeth Motamarry/masquerade-cobol/pipeline")
if str(MASQUERADE_PATH) not in sys.path:
    sys.path.insert(0, str(MASQUERADE_PATH))

from experiments.masquerade_runner import (
    create_initial_repos,
    dict_to_daly_tran,
    run_cbtrn02c_reference,
)

MUTANTS_DIR = Path("experiments/masquerade_mutants")
MUTANTS_DIR.mkdir(parents=True, exist_ok=True)

# Base template for candidate mutant files
BASE_CANDIDATE_CODE = '''"""Masquerade CBTRN02C Candidate Variant: {case_id}
Defect Category: {category}
Description: {description}
"""

from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

MASQUERADE_PATH = Path("c:/Users/Navaneeth Motamarry/masquerade-cobol/pipeline")
if str(MASQUERADE_PATH) not in sys.path:
    sys.path.insert(0, str(MASQUERADE_PATH))

from reimpl.python import cbtrn02c
from reimpl.python.carddemo_data import AccountRecord, CardXrefRecord, TranCatBalRecord, TranRecord
from reimpl.python.cbtrn01c import DalyTranRecord

from experiments.masquerade_runner import create_initial_repos, dict_to_daly_tran

FAIL_INVALID_CARD = 100
FAIL_ACCOUNT_NF = 101
FAIL_OVERLIMIT = 102
FAIL_EXPIRED = 103

{custom_functions}

def post_daily_transactions(
    transactions: list[DalyTranRecord],
    xref_repo: cbtrn02c.XrefRepository,
    account_repo: cbtrn02c.AccountRepository,
    tcatbal_repo: cbtrn02c.TcatbalRepository,
    logger: Callable[[str], None] = print,
) -> cbtrn02c.PostResult:
    result = cbtrn02c.PostResult()
    logger("START OF EXECUTION OF PROGRAM CBTRN02C")

    for tran in transactions:
{body_loop}

    return result


def run_candidate(inp: dict[str, Any]) -> dict[str, Any]:
    xref_repo, acct_repo, tcat_repo = create_initial_repos()
    tran = dict_to_daly_tran(inp)
    res = post_daily_transactions([tran], xref_repo, acct_repo, tcat_repo, logger=lambda s: None)

    reject_details = [
        {{"id": r.tran_data.tran_id, "reason": r.fail_reason, "desc": r.fail_reason_desc}}
        for r in res.rejected_records
    ]
    posted_ids = [t.tran_id for t in res.posted_transactions]

    acct1 = acct_repo.find(12345678901)
    acct1_bal = str(acct1.acct_curr_cyc_credit) if acct1 else "0.00"
    acct2 = acct_repo.find(12345678902)
    acct2_bal = str(acct2.acct_curr_cyc_credit) if acct2 else "0.00"
    tcat1 = tcat_repo.find(12345678901, "01", 1)
    tcat1_bal = str(tcat1.tran_cat_bal) if tcat1 else "0.00"

    return {{
        "status": "SUCCESS" if res.return_code == 0 else "ERROR",
        "return_code": res.return_code,
        "transaction_count": res.transaction_count,
        "reject_count": res.reject_count,
        "posted_count": len(res.posted_transactions),
        "posted_ids": posted_ids,
        "reject_details": reject_details,
        "acct1_cyc_credit": acct1_bal,
        "acct2_cyc_credit": acct2_bal,
        "tcat1_balance": tcat1_bal,
    }}
'''

# Canonical processing loop body
STANDARD_LOOP_BODY = '''        result.transaction_count += 1
        fail_reason = 0
        fail_desc = ""
        xref = None
        acct = None

        xref = xref_repo.find_by_card(tran.tran_card_num)
        if xref is None:
            fail_reason = FAIL_INVALID_CARD
            fail_desc = "INVALID CARD NUMBER FOUND"
        else:
            acct = account_repo.find(xref.xref_acct_id)
            if acct is None:
                fail_reason = FAIL_ACCOUNT_NF
                fail_desc = "ACCOUNT RECORD NOT FOUND"
            else:
                temp_bal = (
                    acct.acct_curr_cyc_credit
                    - acct.acct_curr_cyc_debit
                    + Decimal(str(tran.tran_amt))
                )
                if acct.acct_credit_limit < temp_bal:
                    fail_reason = FAIL_OVERLIMIT
                    fail_desc = "OVERLIMIT TRANSACTION"
                if fail_reason == 0:
                    tran_date = tran.tran_orig_ts[:10] if tran.tran_orig_ts else ""
                    if acct.acct_expiration_date < tran_date:
                        fail_reason = FAIL_EXPIRED
                        fail_desc = "TRANSACTION RECEIVED AFTER ACCT EXPIRATION"

        if fail_reason == 0 and xref is not None and acct is not None:
            acct.acct_curr_cyc_credit += Decimal(str(tran.tran_amt))
            account_repo.update(acct)

            existing_tcat = tcatbal_repo.find(
                acct.acct_id, tran.tran_type_cd, tran.tran_cat_cd
            )
            if existing_tcat:
                existing_tcat.tran_cat_bal += Decimal(str(tran.tran_amt))
                tcatbal_repo.upsert(existing_tcat)
            else:
                new_tcat = TranCatBalRecord(
                    trancat_acct_id=acct.acct_id,
                    trancat_type_cd=tran.tran_type_cd,
                    trancat_cd=tran.tran_cat_cd,
                    tran_cat_bal=Decimal(str(tran.tran_amt)),
                )
                tcatbal_repo.upsert(new_tcat)

            posted = TranRecord(
                tran_id=tran.tran_id,
                tran_type_cd=tran.tran_type_cd,
                tran_cat_cd=tran.tran_cat_cd,
                tran_source=tran.tran_source,
                tran_desc=tran.tran_desc,
                tran_amt=Decimal(str(tran.tran_amt)),
                tran_card_num=tran.tran_card_num,
                tran_merchant_id=tran.tran_merchant_id,
                tran_merchant_name=tran.tran_merchant_name,
                tran_merchant_city=tran.tran_merchant_city,
                tran_merchant_zip=tran.tran_merchant_zip,
                tran_orig_ts=tran.tran_orig_ts,
                tran_proc_ts=tran.tran_proc_ts,
            )
            result.posted_transactions.append(posted)
        else:
            result.reject_count += 1
            result.return_code = 4
            reject = cbtrn02c.RejectRecord(
                tran_data=tran,
                fail_reason=fail_reason,
                fail_reason_desc=fail_desc,
            )
            result.rejected_records.append(reject)'''


# Specifications for all 30 cases
CASES_CONFIG: list[dict[str, Any]] = [
    # ── Category 1: Calculation Defects (CALC) ──────────────────────────────────
    {
        "id": "MASQ_CALC_01",
        "category": "CALC",
        "type": "defective",
        "desc": "Inverted debit subtraction in temp_bal calculation (+ debit instead of - debit)",
        "loop_replace": (
            "acct.acct_curr_cyc_credit\n                    - acct.acct_curr_cyc_debit",
            "acct.acct_curr_cyc_credit\n                    + acct.acct_curr_cyc_debit",
        ),
    },
    {
        "id": "MASQ_CALC_02",
        "category": "CALC",
        "type": "defective",
        "desc": "Boundary defect: credit limit check uses <= instead of <",
        "loop_replace": (
            "if acct.acct_credit_limit < temp_bal:",
            "if acct.acct_credit_limit <= temp_bal:",
        ),
    },
    {
        "id": "MASQ_CALC_03",
        "category": "CALC",
        "type": "defective",
        "desc": "Omits transaction amount from temp_bal before evaluating credit limit",
        "loop_replace": (
            "+ Decimal(str(tran.tran_amt))",
            "+ Decimal('0.00')",
        ),
    },
    {
        "id": "MASQ_CALC_04",
        "category": "CALC",
        "type": "defective",
        "desc": "Subtracts transaction amount from cycle credit balance upon posting",
        "loop_replace": (
            "acct.acct_curr_cyc_credit += Decimal(str(tran.tran_amt))",
            "acct.acct_curr_cyc_credit -= Decimal(str(tran.tran_amt))",
        ),
    },
    {
        "id": "MASQ_CALC_05",
        "category": "CALC",
        "type": "defective",
        "desc": "Truncates decimal cents to integer during temp_bal calculation",
        "loop_replace": (
            "temp_bal = (\n                    acct.acct_curr_cyc_credit\n                    - acct.acct_curr_cyc_debit\n                    + Decimal(str(tran.tran_amt))\n                )",
            "temp_bal = Decimal(int(\n                    acct.acct_curr_cyc_credit\n                    - acct.acct_curr_cyc_debit\n                    + Decimal(str(tran.tran_amt))\n                ))",
        ),
    },
    # ── Category 2: Validation Defects (VAL) ────────────────────────────────────
    {
        "id": "MASQ_VAL_01",
        "category": "VAL",
        "type": "defective",
        "desc": "Bypasses card lookup by creating dummy Xref record for unknown cards",
        "loop_replace": (
            "xref = xref_repo.find_by_card(tran.tran_card_num)",
            "xref = xref_repo.find_by_card(tran.tran_card_num) or CardXrefRecord(xref_card_num=tran.tran_card_num, xref_acct_id=12345678901)",
        ),
    },
    {
        "id": "MASQ_VAL_02",
        "category": "VAL",
        "type": "defective",
        "desc": "Skips account record lookup and uses default account on missing record",
        "loop_replace": (
            "acct = account_repo.find(xref.xref_acct_id)",
            "acct = account_repo.find(xref.xref_acct_id) or account_repo.find(12345678901)",
        ),
    },
    {
        "id": "MASQ_VAL_03",
        "category": "VAL",
        "type": "defective",
        "desc": "Inverts expiration date comparison (< becomes >), rejecting valid cards",
        "loop_replace": (
            "if acct.acct_expiration_date < tran_date:",
            "if acct.acct_expiration_date > tran_date:",
        ),
    },
    {
        "id": "MASQ_VAL_04",
        "category": "VAL",
        "type": "defective",
        "desc": "Swaps failure reason codes: assigns 101 for invalid card and 100 for missing account",
        "loop_replace": (
            "fail_reason = FAIL_INVALID_CARD\n            fail_desc = \"INVALID CARD NUMBER FOUND\"",
            "fail_reason = FAIL_ACCOUNT_NF\n            fail_desc = \"ACCOUNT RECORD NOT FOUND\"",
        ),
    },
    {
        "id": "MASQ_VAL_05",
        "category": "VAL",
        "type": "defective",
        "desc": "Fails to record reject reason code when credit limit is exceeded",
        "loop_replace": (
            "fail_reason = FAIL_OVERLIMIT\n                    fail_desc = \"OVERLIMIT TRANSACTION\"",
            "fail_reason = 0\n                    fail_desc = \"OVERLIMIT TRANSACTION\"",
        ),
    },
    # ── Category 3: State Persistence Defects (STATE) ───────────────────────────
    {
        "id": "MASQ_STATE_01",
        "category": "STATE",
        "type": "defective",
        "desc": "Omits account repository balance update on successful transaction",
        "loop_replace": (
            "account_repo.update(acct)",
            "pass  # Omitting account update",
        ),
    },
    {
        "id": "MASQ_STATE_02",
        "category": "STATE",
        "type": "defective",
        "desc": "Omits category balance upsert on successful transaction",
        "loop_replace": (
            "tcatbal_repo.upsert(existing_tcat)",
            "pass  # Omitting tcatbal update",
        ),
    },
    {
        "id": "MASQ_STATE_03",
        "category": "STATE",
        "type": "defective",
        "desc": "Overwrites existing category balance with transaction amount rather than adding",
        "loop_replace": (
            "existing_tcat.tran_cat_bal += Decimal(str(tran.tran_amt))",
            "existing_tcat.tran_cat_bal = Decimal(str(tran.tran_amt))",
        ),
    },
    {
        "id": "MASQ_STATE_04",
        "category": "STATE",
        "type": "defective",
        "desc": "Upserts category balance under wrong account ID (constant 0)",
        "loop_replace": (
            "trancat_acct_id=acct.acct_id,",
            "trancat_acct_id=0,",
        ),
    },
    {
        "id": "MASQ_STATE_05",
        "category": "STATE",
        "type": "defective",
        "desc": "Resets cycle credit to zero before adding transaction amount",
        "loop_replace": (
            "acct.acct_curr_cyc_credit += Decimal(str(tran.tran_amt))",
            "acct.acct_curr_cyc_credit = Decimal(str(tran.tran_amt))",
        ),
    },
    # ── Category 4: Transaction Logging Defects (TX) ────────────────────────────
    {
        "id": "MASQ_TX_01",
        "category": "TX",
        "type": "defective",
        "desc": "Omits append to rejected records list on validation failure",
        "loop_replace": (
            "result.rejected_records.append(reject)",
            "pass  # Dropping reject record",
        ),
    },
    {
        "id": "MASQ_TX_02",
        "category": "TX",
        "type": "defective",
        "desc": "Fails to record transaction amount in posted transaction log",
        "loop_replace": (
            "tran_amt=Decimal(str(tran.tran_amt)),",
            "tran_amt=Decimal('0.00'),",
        ),
    },
    {
        "id": "MASQ_TX_03",
        "category": "TX",
        "type": "defective",
        "desc": "Drops origin timestamp on posted transaction record",
        "loop_replace": (
            "tran_orig_ts=tran.tran_orig_ts,",
            "tran_orig_ts='',",
        ),
    },
    {
        "id": "MASQ_TX_04",
        "category": "TX",
        "type": "defective",
        "desc": "Omits posted transaction record from result posted list",
        "loop_replace": (
            "result.posted_transactions.append(posted)",
            "pass  # Dropping posted transaction record",
        ),
    },
    {
        "id": "MASQ_TX_05",
        "category": "TX",
        "type": "defective",
        "desc": "Suppresses reject failure description text (sets empty string)",
        "loop_replace": (
            "fail_reason_desc=fail_desc,",
            "fail_reason_desc='',",
        ),
    },
    # ── Category 5: Control Flow Defects (FLOW) ─────────────────────────────────
    {
        "id": "MASQ_FLOW_01",
        "category": "FLOW",
        "type": "defective",
        "desc": "Fails to set return code 4 upon transaction rejection",
        "loop_replace": (
            "result.return_code = 4",
            "result.return_code = 0",
        ),
    },
    {
        "id": "MASQ_FLOW_02",
        "category": "FLOW",
        "type": "defective",
        "desc": "Fails to increment reject count on rejected transaction",
        "loop_replace": (
            "result.reject_count += 1",
            "pass",
        ),
    },
    {
        "id": "MASQ_FLOW_03",
        "category": "FLOW",
        "type": "defective",
        "desc": "Fails to increment total transaction count",
        "loop_replace": (
            "result.transaction_count += 1",
            "pass",
        ),
    },
    {
        "id": "MASQ_FLOW_04",
        "category": "FLOW",
        "type": "defective",
        "desc": "Prematurely breaks transaction loop upon first rejection",
        "loop_replace": (
            "result.rejected_records.append(reject)",
            "result.rejected_records.append(reject)\n            break",
        ),
    },
    # ── Category 6: Equivalent Controls (EQ) ────────────────────────────────────
    {
        "id": "MASQ_EQ_01",
        "category": "EQUIV",
        "type": "equivalent",
        "desc": "De Morgan condition refactoring for expiration check",
        "loop_replace": (
            "if acct.acct_expiration_date < tran_date:",
            "if not (tran_date <= acct.acct_expiration_date):",
        ),
    },
    {
        "id": "MASQ_EQ_02",
        "category": "EQUIV",
        "type": "equivalent",
        "desc": "Helper function extraction for temporary balance computation",
        "custom_functions": """def _calc_prospective_bal(credit: Decimal, debit: Decimal, amt: Decimal) -> Decimal:
    return credit - debit + amt
""",
        "loop_replace": (
            "temp_bal = (\n                    acct.acct_curr_cyc_credit\n                    - acct.acct_curr_cyc_debit\n                    + Decimal(str(tran.tran_amt))\n                )",
            "temp_bal = _calc_prospective_bal(acct.acct_curr_cyc_credit, acct.acct_curr_cyc_debit, Decimal(str(tran.tran_amt)))",
        ),
    },
    {
        "id": "MASQ_EQ_03",
        "category": "EQUIV",
        "type": "equivalent",
        "desc": "Explicit Decimal cast on credit limit comparison",
        "loop_replace": (
            "if acct.acct_credit_limit < temp_bal:",
            "if Decimal(str(acct.acct_credit_limit)) < Decimal(str(temp_bal)):",
        ),
    },
    {
        "id": "MASQ_EQ_04",
        "category": "EQUIV",
        "type": "equivalent",
        "desc": "Refactored timestamp slicing using string formatting",
        "loop_replace": (
            "tran_date = tran.tran_orig_ts[:10] if tran.tran_orig_ts else \"\"",
            "tran_date = str(tran.tran_orig_ts)[:10] if tran.tran_orig_ts is not None else \"\"",
        ),
    },
    {
        "id": "MASQ_EQ_05",
        "category": "EQUIV",
        "type": "equivalent",
        "desc": "Explicit elif ladder refactoring for failure condition evaluation",
        "loop_replace": (
            "if acct.acct_credit_limit < temp_bal:\n                    fail_reason = FAIL_OVERLIMIT\n                    fail_desc = \"OVERLIMIT TRANSACTION\"\n                if fail_reason == 0:\n                    tran_date = tran.tran_orig_ts[:10] if tran.tran_orig_ts else \"\"\n                    if acct.acct_expiration_date < tran_date:\n                        fail_reason = FAIL_EXPIRED\n                        fail_desc = \"TRANSACTION RECEIVED AFTER ACCT EXPIRATION\"",
            "if acct.acct_credit_limit < temp_bal:\n                    fail_reason = FAIL_OVERLIMIT\n                    fail_desc = \"OVERLIMIT TRANSACTION\"\n                elif acct.acct_expiration_date < (tran.tran_orig_ts[:10] if tran.tran_orig_ts else \"\"):\n                    fail_reason = FAIL_EXPIRED\n                    fail_desc = \"TRANSACTION RECEIVED AFTER ACCT EXPIRATION\"",
        ),
    },
    {
        "id": "MASQ_EQ_06",
        "category": "EQUIV",
        "type": "equivalent",
        "desc": "Clean reference candidate implementation (unmodified)",
    },
]


def generate_candidates():
    """Generates all 30 candidate mutant and control files."""
    print("Generating 30 standalone candidate files in experiments/masquerade_mutants/...")
    manifest = []

    for cfg in CASES_CONFIG:
        case_id = cfg["id"]
        cat = cfg["category"]
        desc = cfg["desc"]
        custom = cfg.get("custom_functions", "")

        loop_body = STANDARD_LOOP_BODY
        if "loop_replace" in cfg:
            old_str, new_str = cfg["loop_replace"]
            if old_str not in loop_body:
                raise ValueError(f"Target string not found in loop body for {case_id}: {old_str}")
            loop_body = loop_body.replace(old_str, new_str, 1)

        code = BASE_CANDIDATE_CODE.format(
            case_id=case_id,
            category=cat,
            description=desc,
            custom_functions=custom,
            body_loop=loop_body,
        )

        out_path = MUTANTS_DIR / f"candidate_{case_id}.py"
        out_path.write_text(code, encoding="utf-8")
        sha = hashlib.sha256(code.encode("utf-8")).hexdigest()

        manifest.append({
            "case_id": case_id,
            "category": cat,
            "type": cfg["type"],
            "description": desc,
            "file_path": str(out_path).replace("\\", "/"),
            "sha256": sha,
        })
        print(f"  [OK] candidate_{case_id}.py ({cat}, {cfg['type']})")

    manifest_path = Path("results/05_scaling/masquerade_mutants_manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Written manifest to {manifest_path}")
    return manifest


def measure_ground_truth(manifest: list[dict[str, Any]]):
    """Measures empirical trigger rates over 1,000 independent test transactions."""
    print("\nMeasuring sealed ground-truth trigger rates across 1,000 independent transactions...")
    rng = random.Random(42)

    # Generate 1,000 diverse transactions
    cards = [
        "1111222233334444",  # Standard valid
        "2222333344445555",  # Near-limit
        "3333444455556666",  # Expired
        "8888888888888888",  # Missing account
        "9999999999999999",  # Invalid card
    ]

    test_transactions = []
    for i in range(1000):
        card = rng.choice(cards)
        amt = round(rng.uniform(1.0, 150.0), 2)
        year = rng.choice([2023, 2024, 2026])
        date_str = f"{year}-05-01 10:00:00"
        test_transactions.append({
            "tran_id": str(i + 1).zfill(16),
            "tran_card_num": card,
            "tran_amt": str(amt),
            "tran_type_cd": "01",
            "tran_cat_cd": 1,
            "tran_orig_ts": date_str,
        })

    # Precompute reference outputs
    ref_outputs = [run_cbtrn02c_reference(inp) for inp in test_transactions]

    ground_truth = []
    for item in manifest:
        case_id = item["case_id"]
        # Dynamically import candidate
        module_name = f"experiments.masquerade_mutants.candidate_{case_id}"
        mod = __import__(module_name, fromlist=["run_candidate"])
        run_cand = getattr(mod, "run_candidate")

        mismatches = 0
        for inp, ref_out in zip(test_transactions, ref_outputs):
            try:
                c_out = run_cand(inp)
                if c_out != ref_out:
                    mismatches += 1
            except Exception:
                mismatches += 1

        trigger_rate = round(mismatches / len(test_transactions), 4)
        is_equiv = item["type"] == "equivalent"
        status = "EQUIVALENT" if is_equiv else ("DEFECTIVE" if trigger_rate > 0 else "SUBTLE_DEFECT")

        ground_truth.append({
            "case_id": case_id,
            "category": item["category"],
            "intended_type": item["type"],
            "empirical_mismatches": mismatches,
            "total_samples": len(test_transactions),
            "trigger_rate": trigger_rate,
            "ground_truth_label": status,
            "sha256": item["sha256"],
        })
        print(f"  {case_id:18s} | Type: {item['type']:10s} | Trigger: {trigger_rate:6.2%} ({mismatches:4d}/1000) -> Label: {status}")

    gt_path = Path("results/05_scaling/masquerade_ground_truth.json")
    gt_path.write_text(json.dumps(ground_truth, indent=2), encoding="utf-8")
    print(f"Sealed ground-truth records written to {gt_path}")


if __name__ == "__main__":
    m = generate_candidates()
    measure_ground_truth(m)
