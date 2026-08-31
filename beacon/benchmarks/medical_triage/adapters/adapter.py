"""Adapters for Emergency Medical Triage Decision Benchmark."""

from pathlib import Path
import sys

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BENCHMARK_DIR / "legacy"))
sys.path.append(str(BENCHMARK_DIR / "modernized"))

from certification.adapters import LegacyAdapter, ModernizedAdapter
import medical_triage
import medical_triage_v2
import medical_triage_v2_buggy


class MedicalTriageLegacyAdapter(LegacyAdapter):
    def __init__(self):
        super().__init__(
            target_fn=medical_triage.evaluate_medical_triage,
            name="medical_triage_legacy",
            version="1.0.0",
        )


class MedicalTriageModernCleanAdapter(ModernizedAdapter):
    def __init__(self):
        super().__init__(
            target_fn=medical_triage_v2.evaluate_medical_triage_v2,
            name="medical_triage_modern_clean",
            version="2.0.0",
        )


class MedicalTriageModernBuggyAdapter(ModernizedAdapter):
    def __init__(self):
        super().__init__(
            target_fn=medical_triage_v2_buggy.evaluate_medical_triage_v2_buggy,
            name="medical_triage_modern_buggy",
            version="2.0.0-buggy",
        )
