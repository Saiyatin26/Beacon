"""Modernized Retail & Wholesale Discount Pricing Engine (v2.0.0 — Clean & Equivalent).

Refactored, typed, structured modernization preserving 100% of legacy business invariants.
"""

from typing import Any


def calculate_order_pricing_v2(
    order_amount: float,
    customer_tier: str = "STANDARD",
    items_count: int = 1,
    coupon_code: str = "NONE",
    is_express_shipping: bool = False,
) -> dict[str, Any]:
    """Clean modernized equivalent implementation."""
    tier = str(customer_tier).strip().upper()
    amount = float(order_amount)
    items = int(items_count)
    coupon = str(coupon_code).strip().upper()
    express = bool(is_express_shipping)

    if amount <= 0 or items <= 0:
        return {
            "final_price": 0.0,
            "discount_applied_pct": 0.0,
            "shipping_cost": 0.0,
            "approved_for_fulfillment": False,
        }

    # Determine loyalty tier rate
    base_rates = {
        "VIP": 0.20 if amount >= 500.0 else 0.0,
        "GOLD": 0.15 if amount >= 300.0 else 0.0,
        "SILVER": 0.10 if amount >= 200.0 else 0.0,
    }
    tier_discount = base_rates.get(tier, 0.0)

    # Volume discount
    volume_discount = 0.05 if (items >= 50 and amount >= 1000.0) else 0.0

    # Coupon discount
    coupon_rates = {
        "WELCOME20": 0.20,
        "SAVE10": 0.10,
    }
    coupon_discount = coupon_rates.get(coupon, 0.0)

    # Compute capped discount percentage
    total_discount = min(0.35, tier_discount + volume_discount + coupon_discount)

    # Determine shipping cost
    if (tier == "VIP" and amount >= 500.0) or amount >= 1500.0:
        base_shipping = 0.0
    elif amount < 100.0:
        base_shipping = 15.0
    else:
        base_shipping = 5.0

    express_fee = 20.0 if (express and not (tier == "VIP" and amount >= 500.0)) else 0.0
    final_shipping = base_shipping + express_fee

    subtotal = amount * (1.0 - total_discount)
    final_price = round(subtotal + final_shipping, 2)

    return {
        "final_price": final_price,
        "discount_applied_pct": round(total_discount, 4),
        "shipping_cost": round(final_shipping, 2),
        "approved_for_fulfillment": True,
    }
