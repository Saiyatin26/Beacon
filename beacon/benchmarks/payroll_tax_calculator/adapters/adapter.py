"""Adapters for Progressive Payroll & Income Tax Calculation Benchmark."""

from pathlib import Path
import sys

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BENCHMARK_DIR / "legacy"))
sys.path.append(str(BENCHMARK_DIR / "modernized"))

from certification.adapters import LegacyAdapter, ModernizedAdapter
import payroll_calculator
import payroll_calculator_v2
import payroll_calculator_v2_buggy_bracket
import payroll_calculator_v2_buggy_deduction


class PayrollLegacyAdapter(LegacyAdapter):
    def __init__(self):
        super().__init__(
            target_fn=payroll_calculator.calculate_payroll,
            name="payroll_legacy",
            version="1.0.0",
        )


class PayrollModernCleanAdapter(ModernizedAdapter):
    def __init__(self):
        super().__init__(
            target_fn=payroll_calculator_v2.calculate_payroll_v2,
            name="payroll_modern_clean",
            version="2.0.0",
        )


class PayrollModernBuggyBracketAdapter(ModernizedAdapter):
    def __init__(self):
        super().__init__(
            target_fn=payroll_calculator_v2_buggy_bracket.calculate_payroll_v2_buggy_bracket,
            name="payroll_modern_buggy_bracket",
            version="2.0.0-buggy-bracket",
        )


class PayrollModernBuggyDeductionAdapter(ModernizedAdapter):
    def __init__(self):
        super().__init__(
            target_fn=payroll_calculator_v2_buggy_deduction.calculate_payroll_v2_buggy_deduction,
            name="payroll_modern_buggy_deduction",
            version="2.0.0-buggy-deduction",
        )
