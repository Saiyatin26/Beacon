"""Modernized Progressive Payroll & Income Tax Calculation Engine (v2.0.0-buggy-bracket).

Contains an INTENTIONAL BEHAVIORAL REGRESSION:
- Top 30% tax bracket threshold mutated from $80,000 to $120,000.
- Administrative minimum fee of $50.0 erroneously applied to exempt category.
"""

from typing import Any


def calculate_payroll_v2_buggy_bracket(
    gross_salary: float,
    tax_bracket: str = "STANDARD",
    dependents_count: int = 0,
    retirement_contribution: float = 0.0,
    has_health_coverage: bool = True,
) -> dict[str, Any]:
    salary = float(gross_salary)
    bracket = str(tax_bracket).strip().upper()
    deps = int(dependents_count)
    retire = float(retirement_contribution)
    health = bool(has_health_coverage)

    if salary < 1000.0:
        return {
            "taxable_income": 0.0,
            "federal_tax": 0.0,
            "state_tax": 0.0,
            "fica_tax": 0.0,
            "net_pay": 0.0,
            "eligible_for_payroll": False,
        }

    dependent_allowance = deps * 2000.0
    taxable = max(0.0, salary - retire - dependent_allowance)

    # BUG 1: Exempt bracket erroneously charged $50 administrative fee
    # BUG 2: Middle bracket extended to 120,000 instead of 80,000
    if bracket == "EXEMPT":
        federal_tax = 50.0
    elif taxable <= 20000.0:
        federal_tax = taxable * 0.10
    elif taxable <= 120000.0:
        federal_tax = 2000.0 + (taxable - 20000.0) * 0.20
    else:
        federal_tax = 22000.0 + (taxable - 120000.0) * 0.30

    if health and salary < 50000.0 and bracket != "EXEMPT":
        federal_tax = max(0.0, federal_tax - 500.0)

    state_tax = (taxable * 0.05) if (bracket != "EXEMPT" and taxable > 30000.0) else 0.0

    ss_tax = min(salary, 140000.0) * 0.062
    med_tax = salary * 0.0145
    fica_tax = ss_tax + med_tax

    net_pay = round(salary - federal_tax - state_tax - fica_tax - retire, 2)

    return {
        "taxable_income": round(taxable, 2),
        "federal_tax": round(federal_tax, 2),
        "state_tax": round(state_tax, 2),
        "fica_tax": round(fica_tax, 2),
        "net_pay": net_pay,
        "eligible_for_payroll": net_pay > 0.0,
    }
