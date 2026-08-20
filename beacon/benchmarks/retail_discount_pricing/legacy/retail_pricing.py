"""Legacy Retail & Wholesale Discount Pricing Engine (v1.0.0).

Encapsulates legacy business rules for tiered customer loyalty discounts,
volume rebates, coupon codes, and shipping surcharges.
"""

from typing import Any


def calculate_order_pricing(
    order_amount: float,
    customer_tier: str = "STANDARD",
    items_count: int = 1,
    coupon_code: str = "NONE",
    is_express_shipping: bool = False,
) -> dict[str, Any]:
    """Calculates final order pricing according to legacy pricing specifications."""
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

    # 1. Tier Base Discount
    discount_pct = 0.0
    if tier == "VIP" and amount >= 500.0:
        discount_pct = 0.20
    elif tier == "GOLD" and amount >= 300.0:
        discount_pct = 0.15
    elif tier == "SILVER" and amount >= 200.0:
        discount_pct = 0.10

    # 2. Volume Bulk Discount (Additive)
    if items >= 50 and amount >= 1000.0:
        discount_pct += 0.05

    # 3. Coupon Codes
    if coupon == "WELCOME20":
        discount_pct += 0.20
    elif coupon == "SAVE10":
        discount_pct += 0.10

    # Cap maximum allowable discount at 35%
    if discount_pct > 0.35:
        discount_pct = 0.35

    # 4. Calculate Shipping Cost
    shipping = 0.0
    if tier == "VIP" and amount >= 500.0:
        shipping = 0.0
    elif amount >= 1500.0:
        shipping = 0.0
    elif amount < 100.0:
        shipping = 15.0
    else:
        shipping = 5.0

    # Express shipping surcharge
    if express and not (tier == "VIP" and amount >= 500.0):
        shipping += 20.0

    discounted_amount = amount * (1.0 - discount_pct)
    final_price = round(discounted_amount + shipping, 2)

    return {
        "final_price": final_price,
        "discount_applied_pct": round(discount_pct, 4),
        "shipping_cost": round(shipping, 2),
        "approved_for_fulfillment": True,
    }
