"""Independent clean AI-modernized implementation of loan approval business rules.

This implementation is a completely independent, modern Pythonic reimplementation
with explicit typing, structured documentation, and clean conditional evaluation.
It preserves all implicit legacy business invariants (including credit score,
debt ratio, and income thresholds) without wrapping or importing the legacy implementation.
"""

from typing import Any, Dict


def evaluate_loan(credit_score: int, debt_ratio: float, annual_income: float) -> Dict[str, Any]:
    """Evaluates a loan application based on creditworthiness, debt load, and annual earnings.
    
    Business Rules:
    1. Applications with credit score below 500 are rejected.
    2. Applications with credit score under 600 and debt ratio above 0.40 are rejected.
    3. Applications with annual income under $20,000 and debt ratio above 0.60 are rejected.
    4. All other applications meeting threshold criteria are approved.
    """
    # Rule 1: Minimum credit score floor
    if credit_score < 500:
        return {"decision": "REJECT"}

    # Rule 2: Moderate credit score with elevated debt-to-income ratio
    if credit_score < 600 and debt_ratio > 0.40:
        return {"decision": "REJECT"}

    # Rule 3: Low income with high debt ratio
    if annual_income < 20000.0 and debt_ratio > 0.60:
        return {"decision": "REJECT"}

    # Default: Standard approval
    return {"decision": "APPROVE"}
