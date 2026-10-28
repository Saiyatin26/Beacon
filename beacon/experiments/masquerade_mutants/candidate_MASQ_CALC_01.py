"""Masquerade CBTRN02C Candidate Variant: MASQ_CALC_01
Defect Category: CALC
Description: Inverted debit subtraction in temp_bal calculation (+ debit instead of - debit)
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
        result.transaction_count += 1
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
                    + acct.acct_curr_cyc_debit
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
            result.rejected_records.append(reject)

    return result


def run_candidate(inp: dict[str, Any]) -> dict[str, Any]:
    xref_repo, acct_repo, tcat_repo = create_initial_repos()
    tran = dict_to_daly_tran(inp)
    res = post_daily_transactions([tran], xref_repo, acct_repo, tcat_repo, logger=lambda s: None)

    reject_details = [
        {"id": r.tran_data.tran_id, "reason": r.fail_reason, "desc": r.fail_reason_desc}
        for r in res.rejected_records
    ]
    posted_ids = [t.tran_id for t in res.posted_transactions]

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
