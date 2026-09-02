"""Modernized Buggy Emergency Medical Triage Decision Model (Controlled Mutation).

Introduces behavioral regression: oxygen threshold lowered from 90.0 to 80.0.
"""

from typing import Any


def evaluate_medical_triage_v2_buggy(
    heart_rate: int = 80,
    systolic_bp: int = 120,
    spo2: float = 98.0,
    is_responsive: bool = True,
) -> dict[str, Any]:
    """Controlled mutation variant: critical oxygen threshold changed to 80.0."""
    hr = int(heart_rate)
    bp = int(systolic_bp)
    ox = float(spo2)
    resp = bool(is_responsive)

    if not resp or ox < 80.0 or hr > 140 or bp < 80:
        return {"triage_priority": "CRITICAL", "requires_icu": True}
    elif ox < 94.0 or hr > 110 or bp < 90:
        return {"triage_priority": "URGENT", "requires_icu": False}
    return {"triage_priority": "STANDARD", "requires_icu": False}
