# Retail & Wholesale Discount Pricing Benchmark

## Domain & System Overview
This benchmark implements a multi-tier customer pricing, volume rebate, coupon, and shipping calculation engine commonly found in enterprise e-commerce and wholesale order management systems.

## Business Logic & Invariant Specifications
1. **VIP Loyalty Rule**: Orders $\ge \$500$ placed by `VIP` tier customers automatically receive a 20% discount and free standard/express shipping.
2. **Gold Loyalty Rule**: Orders $\ge \$300$ placed by `GOLD` tier customers receive a 15% discount.
3. **Silver Loyalty Rule**: Orders $\ge \$200$ placed by `SILVER` tier customers receive a 10% discount.
4. **Volume Rebate Rule**: Wholesale orders with $\ge 50$ items and order value $\ge \$1,000$ receive an additional 5% bulk rebate.
5. **Coupon Rules**:
   - `WELCOME20` provides 20% discount.
   - `SAVE10` provides 10% discount.
   - Total combined discount is strictly capped at 35%.
6. **Shipping Tariff Rules**:
   - Orders $< \$100$: $\$15$ standard shipping.
   - Orders $\$100 - \$1,499.99$: $\$5$ standard shipping.
   - Orders $\ge \$1,500$: Free shipping ($\$0$).
   - Express option adds $\$20$ surcharge unless waived for qualifying VIP orders.

## Provenance
- **Category**: `REALISTIC`
- **License**: Apache-2.0
- **Legacy Version**: `1.0.0`
- **Modernized Version**: `2.0.0`
- **Controlled Buggy Variants**:
  - `buggy_threshold_v2`: VIP threshold altered from $\$500$ to $\$1,000$.
  - `buggy_operator_v2`: Volume discount condition mutated from `AND` to `OR`.
