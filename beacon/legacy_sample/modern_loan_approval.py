"""A deliberately imperfect 'AI-modernized' rewrite of legacy_loan_approval.py,
for demo purposes. The credit_score < 600 AND debt_ratio > 0.4 rule was silently
dropped during translation — exactly the kind of bug BEACON's Stage 4 should
catch and report as a counterexample (see architecture doc Section 7.4,
Invariant #147 example)."""


def evaluate_loan(credit_score: int, debt_ratio: float, annual_income: float) -> dict:
    decision = "APPROVE"

    if credit_score < 500:
        decision = "REJECT"
    elif annual_income < 20000 and debt_ratio > 0.6:
        decision = "REJECT"
    # BUG: the credit_score < 600 and debt_ratio > 0.4 branch is missing here.

    return {"decision": decision}
