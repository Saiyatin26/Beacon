"""Phase 12 — Benchmark Registry and Lifecycle Manager.

Discovers, registers, validates, and manages external and public benchmarks,
dynamically wiring benchmark adapters into the BEACON AdapterRegistry.
"""

import importlib.util
import json
import logging
from pathlib import Path
import sys
from typing import Any, Optional

from certification.adapter_registry import adapter_registry
from certification.adapters import ImplementationAdapter, LegacyAdapter, ModernizedAdapter
from certification.models import CertificationTestInput
from oracle.models import (
    CompoundCondition,
    OracleConsequence,
    OracleDefinition,
    OraclePredicate,
    OracleProvenance,
    OracleSet,
)
from oracle.registry import registry as oracle_registry
from oracle.serializer import compute_oracle_set_hash

from .dataset_loader import load_dataset_file
from .models import (
    BenchmarkSpec,
    BenchmarkValidationResult,
    DatasetSpec,
    ProvenanceCategory,
    ReproducibilityManifest,
)

logger = logging.getLogger(__name__)

BENCHMARKS_DIR = Path(__file__).resolve().parents[2] / "benchmarks"


class BenchmarkRegistry:
    """Manages discovery, validation, and adapter resolution for BEACON benchmarks."""

    def __init__(self, benchmarks_dir: Optional[Path] = None):
        self._benchmarks_dir = benchmarks_dir or BENCHMARKS_DIR
        self._specs: dict[str, BenchmarkSpec] = {}
        self._legacy_adapters: dict[str, ImplementationAdapter] = {}
        self._modern_adapters: dict[tuple[str, str], ImplementationAdapter] = {}
        self.refresh()

    def refresh(self):
        """Scans benchmarks directory and registers all discovered benchmarks and adapters."""
        self._specs.clear()
        self._legacy_adapters.clear()
        self._modern_adapters.clear()

        # 1. Register Built-in Loan Demo Benchmark
        self._register_builtin_loan_benchmark()

        # 2. Register Built-in Medical Triage Benchmark
        self._register_builtin_medical_benchmark()

        # 3. Discover External Benchmarks in benchmarks/ directory
        if self._benchmarks_dir.exists():
            for bench_path in self._benchmarks_dir.iterdir():
                if bench_path.is_dir() and (bench_path / "metadata.json").exists():
                    self._load_external_benchmark(bench_path)

    def _register_builtin_loan_benchmark(self):
        spec = BenchmarkSpec(
            benchmark_id="loan_demo",
            name="Loan Approval Invariant Mining Benchmark",
            domain="Financial Services & Underwriting",
            description="Core demonstration benchmark mining loan decision invariants against debt, income, and credit score rules.",
            source="BEACON Core Synthetic Demonstration",
            source_url="https://github.com/Saiyatin26/Beacon/legacy_sample",
            license="Apache-2.0",
            language="Python",
            legacy_version="1.0.0",
            modernized_version="2.0.0",
            provenance_category=ProvenanceCategory.CONTROLLED,
            input_schema={
                "credit_score": "int",
                "debt_ratio": "float",
                "annual_income": "float",
            },
            output_schema={
                "decision": "str",
                "approved": "bool",
            },
            dataset_source="legacy_sample/trace_log.json",
            dataset_version="1.0.0",
            legacy_adapter_id="loan_approval_legacy",
            modernized_adapters={
                "clean_v2": "loan_approval_modern_equiv",
                "buggy_v2": "loan_approval_modern_buggy",
            },
            field_bounds={
                "credit_score": (400, 820),
                "debt_ratio": (0.0, 0.9),
                "annual_income": (10000, 150000),
            },
            tags=["loan", "underwriting", "baseline"],
        )
        self._specs[spec.benchmark_id] = spec

    def _register_builtin_medical_benchmark(self):
        spec = BenchmarkSpec(
            benchmark_id="medical_triage",
            name="Emergency Medical Triage Decision Benchmark",
            domain="Healthcare & Critical Care",
            description="Clinical triage priority scoring evaluating vital signs, oxygen saturation, and heart rate thresholds.",
            source="Clinical Guideline Triage Rules",
            source_url="https://github.com/Saiyatin26/Beacon/benchmarks/medical_triage",
            license="MIT",
            language="Python",
            legacy_version="1.0.0",
            modernized_version="2.0.0",
            provenance_category=ProvenanceCategory.CONTROLLED,
            input_schema={
                "heart_rate": "int",
                "systolic_bp": "int",
                "spo2": "float",
                "is_responsive": "bool",
            },
            output_schema={
                "triage_priority": "str",
                "requires_icu": "bool",
            },
            dataset_source="synthetic_clinical_v1",
            dataset_version="1.0.0",
            legacy_adapter_id="medical_triage_legacy",
            modernized_adapters={
                "clean_v2": "medical_triage_modern_clean",
                "buggy_v2": "medical_triage_modern_buggy",
            },
            field_bounds={
                "heart_rate": (40, 200),
                "systolic_bp": (60, 220),
                "spo2": (70.0, 100.0),
            },
            tags=["medical", "healthcare", "triage"],
        )
        self._specs[spec.benchmark_id] = spec

        # Define medical triage functions inline
        def legacy_medical(heart_rate: int = 80, systolic_bp: int = 120, spo2: float = 98.0, is_responsive: bool = True):
            hr = int(heart_rate)
            bp = int(systolic_bp)
            ox = float(spo2)
            resp = bool(is_responsive)
            if not resp or ox < 90.0 or hr > 140 or bp < 80:
                return {"triage_priority": "CRITICAL", "requires_icu": True}
            elif ox < 94.0 or hr > 110 or bp < 90:
                return {"triage_priority": "URGENT", "requires_icu": False}
            return {"triage_priority": "STANDARD", "requires_icu": False}

        def modern_medical_clean(heart_rate: int = 80, systolic_bp: int = 120, spo2: float = 98.0, is_responsive: bool = True):
            return legacy_medical(heart_rate, systolic_bp, spo2, is_responsive)

        def modern_medical_buggy(heart_rate: int = 80, systolic_bp: int = 120, spo2: float = 98.0, is_responsive: bool = True):
            # BUG: Threshold changed from 90.0 to 80.0 for critical oxygen
            hr = int(heart_rate)
            bp = int(systolic_bp)
            ox = float(spo2)
            resp = bool(is_responsive)
            if not resp or ox < 80.0 or hr > 140 or bp < 80:
                return {"triage_priority": "CRITICAL", "requires_icu": True}
            elif ox < 94.0 or hr > 110 or bp < 90:
                return {"triage_priority": "URGENT", "requires_icu": False}
            return {"triage_priority": "STANDARD", "requires_icu": False}

        leg_adp = LegacyAdapter(target_fn=legacy_medical, name="medical_triage_legacy", version="1.0.0")
        mod_clean_adp = ModernizedAdapter(target_fn=modern_medical_clean, name="medical_triage_modern_clean", version="2.0.0")
        mod_buggy_adp = ModernizedAdapter(target_fn=modern_medical_buggy, name="medical_triage_modern_buggy", version="2.0.0-buggy")

        self._legacy_adapters[spec.benchmark_id] = leg_adp
        self._modern_adapters[(spec.benchmark_id, "clean_v2")] = mod_clean_adp
        self._modern_adapters[(spec.benchmark_id, "buggy_v2")] = mod_buggy_adp

        adapter_registry.register_adapter(leg_adp)
        adapter_registry.register_adapter(mod_clean_adp)
        adapter_registry.register_adapter(mod_buggy_adp)

    def _load_external_benchmark(self, bench_dir: Path):
        meta_file = bench_dir / "metadata.json"
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            spec = BenchmarkSpec.model_validate(data)
            self._specs[spec.benchmark_id] = spec

            # Dynamically import adapters from benchmarks/<id>/adapters/adapter.py
            adapter_file = bench_dir / "adapters" / "adapter.py"
            if adapter_file.exists():
                module_name = f"benchmark_{spec.benchmark_id}_adapters"
                spec_mod = importlib.util.spec_from_file_location(module_name, str(adapter_file))
                if spec_mod and spec_mod.loader:
                    mod = importlib.util.module_from_spec(spec_mod)
                    sys.modules[module_name] = mod
                    spec_mod.loader.exec_module(mod)

                    # Look for registered adapters in the module
                    for attr_name in dir(mod):
                        cls = getattr(mod, attr_name)
                        if isinstance(cls, type) and issubclass(cls, ImplementationAdapter) and cls not in (ImplementationAdapter, LegacyAdapter, ModernizedAdapter):
                            try:
                                adp_instance = cls()
                                adapter_registry.register_adapter(adp_instance)
                                if getattr(adp_instance, "role", "") == "legacy":
                                    self._legacy_adapters[spec.benchmark_id] = adp_instance
                                else:
                                    # Match variant
                                    for var_key, adp_id in spec.modernized_adapters.items():
                                        if adp_instance.name == adp_id:
                                            self._modern_adapters[(spec.benchmark_id, var_key)] = adp_instance
                            except Exception as exc:
                                logger.warning(f"Could not instantiate adapter class {attr_name}: {exc}")

        except Exception as exc:
            logger.error(f"Failed to load external benchmark from {bench_dir}: {exc}")

    def list_benchmarks(self) -> list[BenchmarkSpec]:
        """Returns all discovered benchmark specifications."""
        return list(self._specs.values())

    def get_benchmark(self, benchmark_id: str) -> Optional[BenchmarkSpec]:
        """Retrieves a BenchmarkSpec by ID."""
        return self._specs.get(benchmark_id)

    def get_legacy_adapter(self, benchmark_id: str) -> Optional[ImplementationAdapter]:
        """Resolves the legacy ImplementationAdapter for a benchmark."""
        # 1. From local benchmark map
        if benchmark_id in self._legacy_adapters:
            return self._legacy_adapters[benchmark_id]
        
        # 2. From global registry
        spec = self.get_benchmark(benchmark_id)
        if spec and spec.legacy_adapter_id:
            return adapter_registry.get_adapter(spec.legacy_adapter_id)
        return None

    def get_modernized_adapter(self, benchmark_id: str, variant: str = "clean_v2") -> Optional[ImplementationAdapter]:
        """Resolves a modernized ImplementationAdapter variant for a benchmark."""
        # 1. From local benchmark map
        if (benchmark_id, variant) in self._modern_adapters:
            return self._modern_adapters[(benchmark_id, variant)]
        
        # 2. From global registry
        spec = self.get_benchmark(benchmark_id)
        if spec:
            adp_id = spec.modernized_adapters.get(variant)
            if adp_id:
                return adapter_registry.get_adapter(adp_id)
        return None

    def get_input_dataset(self, benchmark_id: str, dataset_name: str = "default") -> list[CertificationTestInput]:
        """Loads and validates a benchmark input dataset."""
        spec = self.get_benchmark(benchmark_id)
        if not spec:
            raise ValueError(f"Unknown benchmark '{benchmark_id}'")

        bench_dir = self._benchmarks_dir / benchmark_id
        
        # Determine dataset path
        if dataset_name == "validation":
            file_path = bench_dir / "dataset" / "validation.json"
        else:
            # Look for eval dataset file in dataset/
            dataset_dir = bench_dir / "dataset"
            if dataset_dir.exists():
                json_files = list(dataset_dir.glob("*eval*.json")) or list(dataset_dir.glob("*.json"))
                file_path = json_files[0] if json_files else bench_dir / "dataset" / "validation.json"
            else:
                file_path = bench_dir / "dataset" / "validation.json"

        if file_path.exists():
            inputs, _ = load_dataset_file(file_path, spec.input_schema, benchmark_id=benchmark_id)
            return inputs

        # Fallback for loan demo / medical triage synthetic generation
        from certification.input_generator import generate_certification_test_suite
        oracles = self.get_or_create_oracle_set(benchmark_id).oracles
        return generate_certification_test_suite(
            oracles=oracles,
            field_bounds=spec.field_bounds,
            n_diverse_samples=50,
            seed=42,
        )

    def validate_benchmark(self, benchmark_id: str) -> BenchmarkValidationResult:
        """Runs pre-flight validation on benchmark schemas, adapters, and datasets."""
        spec = self.get_benchmark(benchmark_id)
        if not spec:
            return BenchmarkValidationResult(
                benchmark_id=benchmark_id,
                is_valid=False,
                errors=[f"Benchmark '{benchmark_id}' not found in registry."],
            )

        passed: list[str] = []
        errors: list[str] = []
        warnings: list[str] = []
        mod_status: dict[str, str] = {}

        # 1. Validate Legacy Adapter
        leg_adp = self.get_legacy_adapter(benchmark_id)
        leg_status = "OK" if leg_adp else "MISSING"
        if leg_adp:
            passed.append(f"Legacy adapter '{leg_adp.name}' resolved successfully.")
        else:
            errors.append(f"Legacy adapter '{spec.legacy_adapter_id}' could not be resolved.")

        # 2. Validate Modernized Adapters
        for var_name, adp_id in spec.modernized_adapters.items():
            mod_adp = self.get_modernized_adapter(benchmark_id, var_name)
            if mod_adp:
                mod_status[var_name] = "OK"
                passed.append(f"Modernized adapter variant '{var_name}' ({adp_id}) resolved.")
            else:
                mod_status[var_name] = "MISSING"
                errors.append(f"Modernized adapter variant '{var_name}' ({adp_id}) missing.")

        # 3. Validate Dataset Loading
        record_count = 0
        checksum = ""
        try:
            inputs = self.get_input_dataset(benchmark_id, dataset_name="default")
            record_count = len(inputs)
            if inputs:
                passed.append(f"Successfully loaded and validated {record_count} dataset inputs.")
                # Test execution of legacy adapter on first input
                if leg_adp:
                    obs = leg_adp.execute(inputs[0].values, input_id=inputs[0].input_id)
                    if obs.execution_status == "SUCCESS":
                        passed.append("Legacy adapter executed sample record without exception.")
                    else:
                        errors.append(f"Legacy adapter execution error on sample: {obs.error_message}")
            else:
                warnings.append("Dataset returned zero records.")
        except Exception as exc:
            errors.append(f"Dataset validation failed: {exc}")

        is_valid = len(errors) == 0 and leg_status == "OK"
        return BenchmarkValidationResult(
            benchmark_id=benchmark_id,
            is_valid=is_valid,
            checks_passed=passed,
            errors=errors,
            warnings=warnings,
            legacy_adapter_status=leg_status,
            modernized_adapters_status=mod_status,
            dataset_record_count=record_count,
            dataset_checksum=checksum,
        )

    def get_or_create_oracle_set(self, benchmark_id: str) -> OracleSet:
        """Constructs, compiles, and registers a standard OracleSet for the benchmark."""
        set_id = f"SET-{benchmark_id.upper()}"
        existing = oracle_registry.get_oracle_set(set_id)
        if existing:
            return existing

        from common.models import CandidateInvariant
        from oracle.compiler import compile_candidate_to_oracle

        candidates: list[CandidateInvariant] = []

        if benchmark_id == "retail_discount_pricing":
            c1 = CandidateInvariant(
                invariant_id="INV-RETAIL-1",
                condition="customer_tier == 'VIP' and order_amount >= 500.0 and coupon_code == 'NONE' and items_count < 50",
                consequence="discount_applied_pct == 0.20",
                source_file="retail_pricing.py",
                domain="E-Commerce & Retail Supply Chain",
                severity="critical",
                confidence=1.0,
                status="graduated",
            )
            c2 = CandidateInvariant(
                invariant_id="INV-RETAIL-2",
                condition="order_amount >= 1500.0 and is_express_shipping == False",
                consequence="shipping_cost == 0.0",
                source_file="retail_pricing.py",
                domain="E-Commerce & Retail Supply Chain",
                severity="high",
                confidence=0.95,
                status="graduated",
            )
            c3 = CandidateInvariant(
                invariant_id="INV-RETAIL-3",
                condition="order_amount >= 10.0 and items_count >= 1",
                consequence="approved_for_fulfillment == True",
                source_file="retail_pricing.py",
                domain="E-Commerce & Retail Supply Chain",
                severity="high",
                confidence=0.95,
                status="graduated",
            )
            candidates = [c1, c2, c3]

        elif benchmark_id == "payroll_tax_calculator":
            c1 = CandidateInvariant(
                invariant_id="INV-PAYROLL-1",
                condition="tax_bracket == 'EXEMPT'",
                consequence="federal_tax == 0.0",
                source_file="payroll_calculator.py",
                domain="Public Finance & Human Resources",
                severity="critical",
                confidence=1.0,
                status="graduated",
            )
            c2 = CandidateInvariant(
                invariant_id="INV-PAYROLL-2",
                condition="gross_salary >= 1000.0",
                consequence="eligible_for_payroll == True",
                source_file="payroll_calculator.py",
                domain="Public Finance & Human Resources",
                severity="high",
                confidence=0.95,
                status="graduated",
            )
            c3 = CandidateInvariant(
                invariant_id="INV-PAYROLL-3",
                condition="tax_bracket == 'EXEMPT' and gross_salary >= 1000.0",
                consequence="state_tax == 0.0",
                source_file="payroll_calculator.py",
                domain="Public Finance & Human Resources",
                severity="high",
                confidence=0.95,
                status="graduated",
            )
            candidates = [c1, c2, c3]

        elif benchmark_id == "medical_triage":
            c1 = CandidateInvariant(
                invariant_id="INV-MED-1",
                condition="spo2 < 90.0",
                consequence="triage_priority == 'CRITICAL'",
                source_file="medical_triage.py",
                domain="Healthcare & Critical Care",
                severity="critical",
                confidence=1.0,
                status="graduated",
            )
            candidates = [c1]

        else: # loan_demo
            c1 = CandidateInvariant(
                invariant_id="INV-LOAN-1",
                condition="credit_score >= 700",
                consequence="approved == True",
                source_file="legacy_loan_approval.py",
                domain="Financial Services & Underwriting",
                severity="high",
                confidence=0.95,
                status="graduated",
            )
            candidates = [c1]

        # Compile and register oracles
        oracles: list[OracleDefinition] = []
        for cand in candidates:
            oracle = compile_candidate_to_oracle(cand)
            registered_oracle = oracle_registry.register_oracle(oracle)
            oracles.append(registered_oracle)

        hashes = [o.content_hash for o in oracles]
        set_hash = compute_oracle_set_hash(hashes)
        oracle_set = OracleSet(
            oracle_set_id=set_id,
            name=f"{benchmark_id} Oracle Set",
            domain=oracles[0].domain if oracles else "default",
            oracle_ids=[o.oracle_id for o in oracles],
            oracles=oracles,
            oracle_set_hash=set_hash,
        )
        oracle_registry.register_oracle_set(oracle_set)
        return oracle_set


# Module-level default benchmark registry singleton
benchmark_registry = BenchmarkRegistry()
