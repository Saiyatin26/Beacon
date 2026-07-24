"""Stand-in for a 30-year-old legacy system. This is what BEACON is supposed to
discover the hidden rules of, purely by watching it run — there is deliberately
no comment or test anywhere near the buried rule below.

Run legacy_sample/generate_traces.py to produce trace_log.json from this file.
"""


def evaluate_loan(credit_score: int, debt_ratio: float, annual_income: float) -> dict:
    decision = "APPROVE"

    if credit_score < 500:
        decision = "REJECT"
    elif credit_score < 600 and debt_ratio > 0.4:
        # <-- this branch is the undocumented invariant BEACON should mine:
        # credit_score < 600 AND debt_ratio > 0.4 -> REJECT
        decision = "REJECT"
    elif annual_income < 20000 and debt_ratio > 0.6:
        decision = "REJECT"

    return {"decision": decision}
