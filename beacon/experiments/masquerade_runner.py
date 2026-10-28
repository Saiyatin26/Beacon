"""BEACON Independent Benchmark: Execution Harness for Masquerade CBTRN02C.

Provides the reference execution engine, initial database fixtures, canonical transaction
input representations, and rule classification for AWS CardDemo CBTRN02C
(Daily Transaction Posting Batch).
"""

from __future__ import annotations

import copy
from decimal import Decimal
import os
from pathlib import Path
import sys
from typing import Any, Callable

# Ensure masquerade pipeline is in sys.path
MASQUERADE_PATH = Path("c:/Users/Navaneeth Motamarry/masquerade-cobol/pipeline")
if str(MASQUERADE_PATH) not in sys.path:
    sys.path.insert(0, str(MASQUERADE_PATH))

from reimpl.python import cbtrn02c
from reimpl.python.carddemo_data import AccountRecord, CardXrefRecord, TranCatBalRecord
from reimpl.python.cbtrn01c import DalyTranRecord

# 8 Core Specification Rules for CBTRN02C
CBTRN02C_RULES = [
    "RULE_01_CARD_XREF_LOOKUP",
    "RULE_02_ACCOUNT_LOOKUP",
    "RULE_03_OVERLIMIT_CHECK",
    "RULE_04_EXPIRATION_DATE_CHECK",
    "RULE_05_ACCOUNT_BALANCE_UPDATE",
    "RULE_06_TCATBAL_UPSERT",
    "RULE_07_TRANSACT_LOGGING",
    "RULE_08_REJECT_LOGGING",
]


def create_initial_repos() -> tuple[
    cbtrn02c.XrefRepository,
    cbtrn02c.AccountRepository,
    cbtrn02c.TcatbalRepository,
]:
    """Creates a standardized, clean initial database state for CBTRN02C."""
    xrefs = {
        "1111222233334444": CardXrefRecord(
            xref_card_num="1111222233334444", xref_acct_id=12345678901
        ),
        "2222333344445555": CardXrefRecord(
            xref_card_num="2222333344445555", xref_acct_id=12345678902
        ),
        "3333444455556666": CardXrefRecord(
            xref_card_num="3333444455556666", xref_acct_id=12345678903
        ),
        "4444555566667777": CardXrefRecord(
            xref_card_num="4444555566667777", xref_acct_id=12345678904
        ),
        "8888888888888888": CardXrefRecord(
            xref_card_num="8888888888888888", xref_acct_id=99999999999
        ),  # Points to non-existent acct
    }

    accounts = {
        12345678901: AccountRecord(
            acct_id=12345678901,
            acct_active_status="Y",
            acct_credit_limit=Decimal("5000.00"),
            acct_curr_cyc_credit=Decimal("100.00"),
            acct_curr_cyc_debit=Decimal("0.00"),
            acct_expiration_date="2025-12-31",
        ),
        12345678902: AccountRecord(
            acct_id=12345678902,
            acct_active_status="Y",
            acct_credit_limit=Decimal("1000.00"),
            acct_curr_cyc_credit=Decimal("950.00"),
            acct_curr_cyc_debit=Decimal("0.00"),
            acct_expiration_date="2025-12-31",
        ),
        12345678903: AccountRecord(
            acct_id=12345678903,
            acct_active_status="Y",
            acct_credit_limit=Decimal("2000.00"),
            acct_curr_cyc_credit=Decimal("50.00"),
            acct_curr_cyc_debit=Decimal("0.00"),
            acct_expiration_date="2022-01-01",  # Expired
        ),
        12345678904: AccountRecord(
            acct_id=12345678904,
            acct_active_status="N",  # Inactive
            acct_credit_limit=Decimal("3000.00"),
            acct_curr_cyc_credit=Decimal("200.00"),
            acct_curr_cyc_debit=Decimal("0.00"),
            acct_expiration_date="2025-12-31",
        ),
    }

    tcatbals = {
        (12345678901, "01", 1): TranCatBalRecord(
            trancat_acct_id=12345678901,
            trancat_type_cd="01",
            trancat_cd=1,
            tran_cat_bal=Decimal("100.00"),
        )
    }

    return (
        cbtrn02c.XrefRepository(xrefs),
        cbtrn02c.AccountRepository(accounts),
        cbtrn02c.TcatbalRepository(tcatbals),
    )


def dict_to_daly_tran(inp: dict[str, Any]) -> DalyTranRecord:
    """Converts a generic dictionary test input into a DalyTranRecord."""
    amt_raw = inp.get("tran_amt", "50.00")
    try:
        amt = Decimal(str(amt_raw))
    except Exception:
        amt = Decimal("50.00")

    return DalyTranRecord(
        tran_id=str(inp.get("tran_id", "0000000000000001")).zfill(16),
        tran_card_num=str(inp.get("tran_card_num", "1111222233334444")).strip(),
        tran_type_cd=str(inp.get("tran_type_cd", "01")).strip(),
        tran_cat_cd=int(inp.get("tran_cat_cd", 1)),
        tran_source=str(inp.get("tran_source", "POS")).strip(),
        tran_desc=str(inp.get("tran_desc", "Daily Purchase")).strip(),
        tran_amt=amt,
        tran_merchant_id=int(inp.get("tran_merchant_id", 1001)),
        tran_merchant_name=str(inp.get("tran_merchant_name", "Merchant A")).strip(),
        tran_merchant_city=str(inp.get("tran_merchant_city", "New York")).strip(),
        tran_merchant_zip=str(inp.get("tran_merchant_zip", "10001")).strip(),
        tran_orig_ts=str(inp.get("tran_orig_ts", "2024-05-01 10:00:00")),
        tran_proc_ts=str(inp.get("tran_proc_ts", "2024-05-01 10:00:00")),
    )


def classify_cbtrn02c_rules(inp: dict[str, Any]) -> set[str]:
    """Maps a test transaction input to the CBTRN02C specification rules exercised."""
    rules = set()
    card = str(inp.get("tran_card_num", "")).strip()

    if card == "9999999999999999":
        rules.add("RULE_01_CARD_XREF_LOOKUP")
        rules.add("RULE_08_REJECT_LOGGING")
        return rules

    if card == "8888888888888888":
        rules.add("RULE_01_CARD_XREF_LOOKUP")
        rules.add("RULE_02_ACCOUNT_LOOKUP")
        rules.add("RULE_08_REJECT_LOGGING")
        return rules

    amt = Decimal(str(inp.get("tran_amt", "50.00")))
    if card == "2222333344445555" and amt > Decimal("50.00"):
        # Triggers overlimit (950 + amt > 1000)
        rules.add("RULE_01_CARD_XREF_LOOKUP")
        rules.add("RULE_02_ACCOUNT_LOOKUP")
        rules.add("RULE_03_OVERLIMIT_CHECK")
        rules.add("RULE_08_REJECT_LOGGING")
        return rules

    orig_ts = str(inp.get("tran_orig_ts", "2024-05-01 10:00:00"))[:10]
    if card == "3333444455556666" or orig_ts > "2025-12-31":
        # Triggers expiration
        rules.add("RULE_01_CARD_XREF_LOOKUP")
        rules.add("RULE_02_ACCOUNT_LOOKUP")
        rules.add("RULE_04_EXPIRATION_DATE_CHECK")
        rules.add("RULE_08_REJECT_LOGGING")
        return rules

    # Standard valid transaction flow
    rules.add("RULE_01_CARD_XREF_LOOKUP")
    rules.add("RULE_02_ACCOUNT_LOOKUP")
    rules.add("RULE_03_OVERLIMIT_CHECK")
    rules.add("RULE_04_EXPIRATION_DATE_CHECK")
    rules.add("RULE_05_ACCOUNT_BALANCE_UPDATE")
    rules.add("RULE_06_TCATBAL_UPSERT")
    rules.add("RULE_07_TRANSACT_LOGGING")
    return rules


def run_cbtrn02c_reference(inp: dict[str, Any]) -> dict[str, Any]:
    """Executes the reference CBTRN02C implementation on a transaction input.

    Returns a canonical serializable dictionary of state and outcome observations.
    """
    xref_repo, acct_repo, tcat_repo = create_initial_repos()
    tran = dict_to_daly_tran(inp)

    res = cbtrn02c.post_daily_transactions(
        transactions=[tran],
        xref_repo=xref_repo,
        account_repo=acct_repo,
        tcatbal_repo=tcat_repo,
        logger=lambda s: None,
    )

    reject_details = [
        {"id": r.tran_data.tran_id, "reason": r.fail_reason, "desc": r.fail_reason_desc}
        for r in res.rejected_records
    ]
    posted_ids = [t.tran_id for t in res.posted_transactions]

    # Sample updated account 12345678901 balance if modified
    acct1 = acct_repo.find(12345678901)
    acct1_bal = str(acct1.acct_curr_cyc_credit) if acct1 else "0.00"

    acct2 = acct_repo.find(12345678902)
    acct2_bal = str(acct2.acct_curr_cyc_credit) if acct2 else "0.00"

    tcat1 = tcat_repo.find(12345678901, "01", 1)
    tcat1_bal = str(tcat1.tran_cat_bal) if tcat1 else "0.00"

    return {
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
    }
