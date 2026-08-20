"""Adapters for Retail & Wholesale Discount Pricing Benchmark."""

from pathlib import Path
import sys

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BENCHMARK_DIR / "legacy"))
sys.path.append(str(BENCHMARK_DIR / "modernized"))

from certification.adapters import LegacyAdapter, ModernizedAdapter
import retail_pricing
import retail_pricing_v2
import retail_pricing_v2_buggy_threshold
import retail_pricing_v2_buggy_operator


class RetailPricingLegacyAdapter(LegacyAdapter):
    def __init__(self):
        super().__init__(
            target_fn=retail_pricing.calculate_order_pricing,
            name="retail_pricing_legacy",
            version="1.0.0",
        )


class RetailPricingModernCleanAdapter(ModernizedAdapter):
    def __init__(self):
        super().__init__(
            target_fn=retail_pricing_v2.calculate_order_pricing_v2,
            name="retail_pricing_modern_clean",
            version="2.0.0",
        )


class RetailPricingModernBuggyThresholdAdapter(ModernizedAdapter):
    def __init__(self):
        super().__init__(
            target_fn=retail_pricing_v2_buggy_threshold.calculate_order_pricing_v2_buggy_threshold,
            name="retail_pricing_modern_buggy_threshold",
            version="2.0.0-buggy-threshold",
        )


class RetailPricingModernBuggyOperatorAdapter(ModernizedAdapter):
    def __init__(self):
        super().__init__(
            target_fn=retail_pricing_v2_buggy_operator.calculate_order_pricing_v2_buggy_operator,
            name="retail_pricing_modern_buggy_operator",
            version="2.0.0-buggy-operator",
        )
