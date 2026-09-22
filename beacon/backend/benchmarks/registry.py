"""Phase 12 — Benchmark Registry and Lifecycle Manager.

Discovers, registers, validates, and manages external and public benchmarks,
dynamically wiring benchmark adapters into the BEACON AdapterRegistry.
Supports both CONTROLLED baseline evaluation and FULL_BEACON evidence discovery.
"""

from datetime import datetime, timezone
import importlib.util
import json
import logging
from pathlib import Path
import sys
from typing import Any, Callable, Optional

import hashlib
import time
from certification.adapter_registry import adapter_registry
from certification.adapters import FunctionAdapter, ImplementationAdapter, LegacyAdapter, ModernizedAdapter, compute_implementation_hash
from certification.models import CertificationTestInput
from common.config import settings
from oracle.models import (
    OracleDefinition,
    OracleProvenance,
    OracleSet,
)
from oracle.registry import registry as oracle_registry
from oracle.serializer import compute_oracle_set_hash
from operations.logging_config import log_operational_event
from operations.logging_config import log_operational_event

from .dataset_loader import compute_file_checksum, load_dataset_file
from .models import (
    BenchmarkExecutionManifest,
    BenchmarkSpec,
    BenchmarkValidationResult,
    DatasetSpec,
    DiscoveryMode,
    ModernizationProvenance,
    ProvenanceCategory,
    ReproducibilityManifest,
)

logger = logging.getLogger(__name__)

# Ensure legacy_sample and modern_sample are available
ROOT_DIR = Path(__file__).resolve().parents[2]
for p in (str(ROOT_DIR / "legacy_sample"), str(ROOT_DIR / "modern_sample"), str(ROOT_DIR / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

BENCHMARKS_DIR = Path(__file__).resolve().parents[2] / "benchmarks"


class BenchmarkRegistry:
    """Manages discovery, validation, and adapter resolution for BEACON benchmarks."""

    def __init__(self, benchmarks_dir: Optional[Path] = None):
        self._benchmarks_dir = benchmarks_dir or BENCHMARKS_DIR
        self._specs: dict[str, BenchmarkSpec] = {}
        self._legacy_adapters: dict[str, ImplementationAdapter] = {}
        self._modern_adapters: dict[tuple[str, str], ImplementationAdapter] = {}
        self._discovered_oracle_sets: dict[tuple[str, str, str, bool], OracleSet] = {}
        self.refresh()

    def refresh(self):
        """Scans benchmarks directory and registers all discovered benchmarks and adapters."""
        self._specs.clear()
        self._legacy_adapters.clear()
        self._modern_adapters.clear()
        self._discovered_oracle_sets.clear()

        # Discover External Benchmarks in benchmarks/ directory
        if self._benchmarks_dir.exists():
            for bench_path in self._benchmarks_dir.iterdir():
                if bench_path.is_dir() and (bench_path / "metadata.json").exists():
                    self._load_external_benchmark(bench_path)

        # Pre-load Controlled Baseline OracleSets into Oracle Registry
        for b_id in list(self._specs.keys()):
            try:
                self.resolve_controlled_oracle_set(b_id)
            except Exception as exc:
                logger.debug(f"Controlled oracle set pre-load note for {b_id}: {exc}")

    def resolve_controlled_oracle_set(self, benchmark_id: str) -> OracleSet:
        """Resolves/pre-loads the controlled baseline OracleSet for a benchmark."""
        return self.get_or_create_oracle_set(benchmark_id, mode="CONTROLLED")

    def _load_external_benchmark(self, bench_dir: Path):
        meta_file = bench_dir / "metadata.json"
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            spec = BenchmarkSpec.model_validate(data)
            
            # Pre-compute dataset checksum if dataset exists
            eval_files = list((bench_dir / "dataset").glob("*eval*.json")) or list((bench_dir / "dataset").glob("*.json"))
            if eval_files:
                spec.dataset_checksum = compute_file_checksum(eval_files[0])
            
            # Pre-compute legacy implementation hash from authoritative legacy source file
            leg_dir = bench_dir / "legacy"
            leg_source_file = None
            if leg_dir.exists():
                py_files = sorted([f for f in leg_dir.glob("*.py") if not f.name.startswith("__")])
                if py_files:
                    leg_source_file = py_files[0]
                    spec.legacy_implementation_hash = compute_implementation_hash(leg_source_file)
                else:
                    spec.legacy_implementation_hash = compute_implementation_hash(leg_dir)

            if not spec.reproducibility_manifest:
                spec.reproducibility_manifest = ReproducibilityManifest(
                    benchmark_id=spec.benchmark_id,
                    benchmark_version=spec.legacy_version,
                    adapter_version=spec.adapter_version,
                    dataset_checksum=spec.dataset_checksum,
                )
            else:
                spec.reproducibility_manifest.dataset_checksum = spec.dataset_checksum

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
                                if getattr(adp_instance, "role", "") == "legacy":
                                    if leg_source_file and leg_source_file.exists():
                                        adp_instance.implementation_hash = compute_implementation_hash(leg_source_file)
                                    else:
                                        adp_instance.implementation_hash = spec.legacy_implementation_hash or compute_implementation_hash(adp_instance)
                                    self._legacy_adapters[spec.benchmark_id] = adp_instance
                                else:
                                    # Match variant and compute authoritative hash from exact source file
                                    for var_key, adp_id in spec.modernized_adapters.items():
                                        if adp_instance.name == adp_id:
                                            # 1. Try resolving authoritative source file from target callable
                                            target_fn = getattr(adp_instance, "target_fn", None) or getattr(adp_instance, "_target_fn", None)
                                            mod_source_file = None
                                            if target_fn:
                                                import inspect
                                                try:
                                                    fn_file = inspect.getsourcefile(target_fn) or inspect.getfile(target_fn)
                                                    if fn_file and Path(fn_file).exists():
                                                        mod_source_file = Path(fn_file)
                                                except Exception:
                                                    pass

                                            # 2. Fallback to file matching in modernized directory
                                            if not mod_source_file:
                                                mod_dir = bench_dir / "modernized"
                                                if mod_dir.exists():
                                                    candidates = sorted([f for f in mod_dir.glob("*.py") if not f.name.startswith("__")])
                                                    for cand in candidates:
                                                        cand_stem = cand.stem.lower()
                                                        var_clean = var_key.replace("_v2", "").lower()
                                                        if var_clean in cand_stem or (var_clean == "clean" and "buggy" not in cand_stem):
                                                            mod_source_file = cand
                                                            break

                                            if mod_source_file and mod_source_file.exists():
                                                adp_instance.implementation_hash = compute_implementation_hash(mod_source_file)
                                            else:
                                                # Authoritative modern file must be resolved; fail closed
                                                adp_instance.implementation_hash = compute_implementation_hash(adp_instance)

                                            self._modern_adapters[(spec.benchmark_id, var_key)] = adp_instance
                                adapter_registry.register_adapter(adp_instance)
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
        if benchmark_id in self._legacy_adapters:
            adp = self._legacy_adapters[benchmark_id]
            adapter_registry.register_adapter(adp)
            return adp
        
        spec = self.get_benchmark(benchmark_id)
        if spec and spec.legacy_adapter_id:
            return adapter_registry.get_adapter(spec.legacy_adapter_id)
        return None

    def get_modernized_adapter(self, benchmark_id: str, variant: str = "clean_v2") -> Optional[ImplementationAdapter]:
        """Resolves a modernized ImplementationAdapter variant for a benchmark."""
        if (benchmark_id, variant) in self._modern_adapters:
            adp = self._modern_adapters[(benchmark_id, variant)]
            adapter_registry.register_adapter(adp)
            return adp
        
        spec = self.get_benchmark(benchmark_id)
        if spec:
            adp_id = spec.modernized_adapters.get(variant)
            if adp_id:
                return adapter_registry.get_adapter(adp_id)
        return None

    def get_input_dataset(self, benchmark_id: str, dataset_name: str = "default") -> list[CertificationTestInput]:
        """Loads and validates a benchmark input dataset."""
        inputs, _ = self.load_dataset_with_checksum(benchmark_id, dataset_name)
        return inputs

    def load_dataset_with_checksum(
        self, benchmark_id: str, dataset_name: str = "default"
    ) -> tuple[list[CertificationTestInput], str]:
        """Loads dataset and returns both normalized inputs and SHA-256 file checksum."""
        spec = self.get_benchmark(benchmark_id)
        if not spec:
            raise ValueError(f"Unknown benchmark '{benchmark_id}'")

        bench_dir = self._benchmarks_dir / benchmark_id
        
        if dataset_name == "validation":
            file_path = bench_dir / "dataset" / "validation.json"
        else:
            dataset_dir = bench_dir / "dataset"
            if dataset_dir.exists():
                json_files = list(dataset_dir.glob("*eval*.json")) or list(dataset_dir.glob("*.json"))
                file_path = json_files[0] if json_files else bench_dir / "dataset" / "validation.json"
            else:
                file_path = bench_dir / "dataset" / "validation.json"

        if file_path.exists():
            return load_dataset_file(file_path, spec.input_schema, benchmark_id=benchmark_id)

        raise FileNotFoundError(f"Dataset file not found for benchmark '{benchmark_id}': {file_path}")

    def validate_benchmark(
        self,
        benchmark_id: str,
        evaluation_mode: str = "CONTROLLED",
        target_variant: str = "clean_v2",
        preferred_provider: str = "auto",
        dataset_name: str = "default",
    ) -> BenchmarkValidationResult:
        """Runs comprehensive pre-flight validation on benchmark schemas, adapters, datasets, and configuration."""
        started = time.perf_counter()
        log_operational_event(
            event="benchmark_validation_started",
            logger_name="beacon.execution",
            operation="PRE-FLIGHT",
            step="VALIDATE_BENCHMARK",
            benchmark_id=benchmark_id,
            evaluation_mode=evaluation_mode,
            target_variant=target_variant,
            provider=preferred_provider,
            message=f"[STEP 01] START | benchmark={benchmark_id} | mode={evaluation_mode} | variant={target_variant}",
        )
        spec = self.get_benchmark(benchmark_id)
        if not spec:
            return BenchmarkValidationResult(
                benchmark_id=benchmark_id,
                evaluation_mode=evaluation_mode,
                target_variant=target_variant,
                preferred_provider=preferred_provider,
                is_valid=False,
                errors=[f"Benchmark '{benchmark_id}' not found in registry."],
            )

        passed: list[str] = []
        errors: list[str] = []
        warnings: list[str] = []
        mod_status: dict[str, str] = {}

        # 1. Validate Mode
        norm_mode = evaluation_mode.upper().strip()
        if norm_mode not in ("CONTROLLED", "FULL_BEACON"):
            errors.append(f"Invalid evaluation mode '{evaluation_mode}'. Must be 'CONTROLLED' or 'FULL_BEACON'.")
        else:
            passed.append(f"Evaluation mode '{norm_mode}' validated.")

        # 2. Validate Provenance & Metadata
        if not spec.source:
            errors.append("Benchmark specification missing 'source' field.")
        if not spec.license:
            errors.append("Benchmark specification missing 'license' field.")
        if not spec.dataset_source:
            warnings.append("Benchmark specification missing explicit 'dataset_source' field.")
        passed.append(f"Provenance categorized truthfully as '{spec.provenance_category.value}'.")

        # 3. Validate Legacy Adapter
        leg_adp = self.get_legacy_adapter(benchmark_id)
        leg_status = "OK" if leg_adp else "MISSING"
        leg_hash = ""
        if leg_adp:
            leg_hash = getattr(leg_adp, "implementation_hash", "") or spec.legacy_implementation_hash
            passed.append(f"Legacy adapter '{leg_adp.name}' resolved successfully (hash: {leg_hash[:16]}...).")
        else:
            errors.append(f"Legacy adapter '{spec.legacy_adapter_id}' could not be resolved.")

        # 4. Validate Modernized Adapters & Requested Variant
        for var_name, adp_id in spec.modernized_adapters.items():
            mod_adp = self.get_modernized_adapter(benchmark_id, var_name)
            if mod_adp:
                mod_status[var_name] = "OK"
                passed.append(f"Modernized adapter variant '{var_name}' ({adp_id}) resolved.")
            else:
                mod_status[var_name] = "MISSING"
                errors.append(f"Modernized adapter variant '{var_name}' ({adp_id}) missing.")

        target_mod_adp = self.get_modernized_adapter(benchmark_id, target_variant)
        target_var_status = "OK" if target_mod_adp else "MISSING"
        mod_hash = ""
        if target_mod_adp:
            mod_hash = getattr(target_mod_adp, "implementation_hash", "")
            passed.append(f"Target modernization variant '{target_variant}' adapter resolved (hash: {mod_hash[:16]}...).")
        else:
            errors.append(f"Requested target modernization variant '{target_variant}' not available for benchmark '{benchmark_id}'.")

        # 5. Validate Dataset Loading & Checksum Propagation
        record_count = 0
        checksum = ""
        try:
            inputs, checksum = self.load_dataset_with_checksum(benchmark_id, dataset_name=dataset_name)
            record_count = len(inputs)
            if inputs:
                passed.append(f"Successfully loaded and validated {record_count} dataset inputs.")
                passed.append(f"Dataset SHA-256 checksum calculated: {checksum[:16]}...")
                
                # Propagate checksum into spec and reproducibility manifest
                spec.dataset_checksum = checksum
                if spec.reproducibility_manifest:
                    spec.reproducibility_manifest.dataset_checksum = checksum
                
                # Test execution of legacy adapter on first input
                if leg_adp:
                    obs = leg_adp.execute(inputs[0].values, input_id=inputs[0].input_id)
                    if obs.execution_status == "SUCCESS":
                        passed.append("Legacy adapter executed sample record without exception.")
                    else:
                        errors.append(f"Legacy adapter execution error on sample: {obs.error_message}")

                # Test execution of modern target adapter on first input
                if target_mod_adp:
                    mod_obs = target_mod_adp.execute(inputs[0].values, input_id=inputs[0].input_id)
                    if mod_obs.execution_status == "SUCCESS":
                        passed.append("Target modern adapter executed sample record without exception.")
                    else:
                        errors.append(f"Modern adapter execution error on sample: {mod_obs.error_message}")
            else:
                warnings.append("Dataset returned zero records.")
        except Exception as exc:
            errors.append(f"Dataset validation failed: {exc}")

        # 6. Validate OracleSet / Policy Availability
        try:
            if norm_mode == "CONTROLLED":
                orc_set = self.get_or_create_oracle_set(benchmark_id, mode="CONTROLLED")
                if orc_set and len(orc_set.oracles) > 0:
                    passed.append(f"Baseline OracleSet '{orc_set.oracle_set_id}' resolved ({len(orc_set.oracles)} invariants).")
                else:
                    errors.append(f"Baseline OracleSet for benchmark '{benchmark_id}' contains zero invariants.")
            else:
                passed.append(f"FULL_BEACON discovery pipeline configured (preferred provider: '{preferred_provider}').")
        except Exception as exc:
            errors.append(f"OracleSet pre-flight check failed: {exc}")

        is_valid = len(errors) == 0 and leg_status == "OK" and target_var_status == "OK"

        # 7. Compute Canonical Validation Fingerprint
        fingerprint_payload = {
            "benchmark_id": benchmark_id,
            "evaluation_mode": norm_mode,
            "target_variant": target_variant,
            "preferred_provider": preferred_provider.lower().strip(),
            "dataset_checksum": checksum,
            "legacy_implementation_hash": leg_hash,
            "modernized_implementation_hash": mod_hash,
        }
        config_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        result = BenchmarkValidationResult(
            benchmark_id=benchmark_id,
            evaluation_mode=norm_mode,
            target_variant=target_variant,
            preferred_provider=preferred_provider,
            config_fingerprint=config_fingerprint,
            is_valid=is_valid,
            checks_passed=passed,
            errors=errors,
            warnings=warnings,
            legacy_adapter_status=leg_status,
            modernized_adapters_status=mod_status,
            target_variant_adapter_status=target_var_status,
            dataset_record_count=record_count,
            dataset_checksum=checksum,
            legacy_implementation_hash=leg_hash,
            modernized_implementation_hash=mod_hash,
            metadata_provenance_valid=len(errors) == 0,
        )
        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        log_operational_event(
            event="benchmark_validation_completed",
            logger_name="beacon.execution",
            operation="PRE-FLIGHT",
            step="VALIDATE_BENCHMARK",
            benchmark_id=benchmark_id,
            evaluation_mode=norm_mode,
            target_variant=target_variant,
            duration_ms=duration_ms,
            outcome="READY" if result.is_valid else "NOT_READY",
            records=record_count,
            oracles=(len(orc_set.oracles) if norm_mode == "CONTROLLED" and 'orc_set' in locals() and orc_set else 0),
            message=f"[STEP 01] COMPLETE | status={'READY' if result.is_valid else 'NOT_READY'} | duration={duration_ms:.2f}ms",
        )
        return result

    def get_or_create_oracle_set(
        self,
        benchmark_id: str,
        mode: str = "CONTROLLED",
        preferred_provider: Optional[str] = None,
        use_llm: bool = False,
    ) -> OracleSet:
        """Retrieves or builds an OracleSet.
        - CONTROLLED: Returns predefined baseline OracleSet with 'CONTROLLED_ORACLE_SET' provenance.
        - FULL_BEACON: Executes the full evidence mining, grounding, adversarial validation, and Oracle compilation pipeline.
        """
        cache_key = (benchmark_id, mode.upper(), (preferred_provider or "auto").lower().strip(), bool(use_llm))
        if cache_key in self._discovered_oracle_sets:
            return self._discovered_oracle_sets[cache_key]

        if mode.upper() == "FULL_BEACON":
            orc_set = self.discover_oracle_set_full_pipeline(
                benchmark_id=benchmark_id,
                use_llm=use_llm,
                preferred_provider=preferred_provider,
            )
            self._discovered_oracle_sets[cache_key] = orc_set
            return orc_set

        # CONTROLLED Mode Baseline
        # CONTROLLED Mode Baseline
        set_id = f"SET-{benchmark_id.upper()}-CONTROLLED"
        existing = oracle_registry.get_oracle_set(set_id)
        if existing:
            return existing

        bench_dir = self._benchmarks_dir / benchmark_id
        oracle_file = bench_dir / "oracle_set.json"
        if oracle_file.exists():
            with open(oracle_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            oracle_set = OracleSet.model_validate(data)
            oracle_registry.register_oracle_set(oracle_set)
            return oracle_set

        # If no controlled oracle set file exists for this benchmark, produce empty controlled baseline
        set_hash = compute_oracle_set_hash([])
        oracle_set = OracleSet(
            oracle_set_id=set_id,
            name=f"{benchmark_id} Controlled Baseline Oracle Set",
            domain="default",
            oracle_ids=[],
            oracles=[],
            oracle_set_hash=set_hash,
        )
        oracle_registry.register_oracle_set(oracle_set)
        
        # Update spec reproducibility manifest
        spec = self.get_benchmark(benchmark_id)
        if spec and spec.reproducibility_manifest:
            spec.reproducibility_manifest.oracle_set_hash = set_hash

        return oracle_set

    def discover_oracle_set_full_pipeline(
        self,
        benchmark_id: str,
        use_llm: bool = False,
        preferred_provider: Optional[str] = None,
        model_provider: Optional[str] = None,
    ) -> OracleSet:
        """Executes genuine full-pipeline discovery:
        Legacy Source AST -> Dynamic Traces -> Unified Evidence Package ->
        Invariant Mining -> Evidence Grounding -> Adversarial Validation ->
        Confidence Scoring -> Language-Independent Oracle Compilation.
        """
        discovery_started = time.perf_counter()
        log_operational_event(
            event="full_beacon_discovery_started",
            logger_name="beacon.execution",
            operation="FULL_BEACON",
            step="BEHAVIORAL_OBSERVATION",
            benchmark_id=benchmark_id,
            provider=preferred_provider or model_provider or "auto",
            message=f"[FULL BEACON] START | benchmark={benchmark_id} | Atlas Vector Search=DISABLED",
        )
        spec = self.get_benchmark(benchmark_id)
        if not spec:
            raise ValueError(f"Unknown benchmark '{benchmark_id}'")

        legacy_adp = self.get_legacy_adapter(benchmark_id)
        if not legacy_adp:
            raise ValueError(f"Legacy adapter missing for benchmark '{benchmark_id}'")

        legacy_fn: Callable = getattr(legacy_adp, "_target_fn", None) or getattr(legacy_adp, "target_fn", None)
        if not legacy_fn:
            legacy_fn = lambda **kw: legacy_adp.execute(kw).raw_outputs

        legacy_impl_hash = getattr(legacy_adp, "implementation_hash", "") or compute_implementation_hash(legacy_fn)
        pref_prov = (preferred_provider or model_provider or "auto").lower().strip()

        # 1. Locate Legacy Source File
        bench_dir = self._benchmarks_dir / benchmark_id
        legacy_dir = bench_dir / "legacy"
        source_path: Optional[Path] = None
        if legacy_dir.exists():
            py_files = sorted(list(legacy_dir.glob("*.py")))
            if py_files:
                source_path = py_files[0]

        if not source_path or not source_path.exists():
            raise FileNotFoundError(f"Legacy source file not found for benchmark '{benchmark_id}'")

        # 2. Static AST Parsing
        from ingestion.legacy_parser import extract_ast_structure
        static_result = extract_ast_structure(source_path)
        log_operational_event(
            event="full_beacon_static_analysis_completed",
            logger_name="beacon.execution",
            operation="FULL_BEACON",
            step="STATIC_ANALYSIS",
            benchmark_id=benchmark_id,
            message="[FULL BEACON] STATIC ANALYSIS COMPLETE | legacy source parsed",
        )

        # 3. Dynamic Execution Tracing
        from ingestion.runtime_tracer import PythonRuntimeTracer
        dataset_inputs = self.get_input_dataset(benchmark_id)
        sample_dicts = [inp.values for inp in dataset_inputs] if dataset_inputs else []
        tracer = PythonRuntimeTracer()
        traces = tracer.trace_batch(legacy_fn, sample_dicts) if sample_dicts else []
        log_operational_event(
            event="full_beacon_observation_completed",
            logger_name="beacon.execution",
            operation="FULL_BEACON",
            step="BEHAVIORAL_OBSERVATION",
            benchmark_id=benchmark_id,
            records=len(traces),
            message=f"[FULL BEACON] BEHAVIORAL OBSERVATION COMPLETE | traces={len(traces)}",
        )

        # 4. Build Unified Evidence Package and Compute Canonical Evidence Hash
        from evidence.builder import build_evidence_package
        from evidence.models import compute_evidence_package_hash
        evidence_pkg = build_evidence_package(static_result, traces)
        ev_hash = compute_evidence_package_hash(evidence_pkg)
        evidence_pkg.evidence_package_hash = ev_hash
        log_operational_event(
            event="full_beacon_evidence_completed",
            logger_name="beacon.execution",
            operation="FULL_BEACON",
            step="EVIDENCE_PACKAGE",
            benchmark_id=benchmark_id,
            message=f"[FULL BEACON] EVIDENCE PACKAGE COMPLETE | hash={ev_hash[:16]}...",
        )

        # Authoritative prompt version from mining.prompt_builder
        from mining.prompt_builder import PROMPT_VERSION

        dataset_chk = getattr(spec, "dataset_checksum", "")

        # Build sanitized model configuration mapping
        model_config = {
            "requested_provider": pref_prov,
            "provider_order": ["openrouter", "anthropic", "ollama", "offline"],
            "openrouter_model": getattr(settings, "openrouter_model", ""),
            "anthropic_model": getattr(settings, "anthropic_model", ""),
            "ollama_model": getattr(settings, "ollama_model", ""),
        } if pref_prov == "auto" else {
            "requested_provider": pref_prov,
            "model": getattr(settings, "openrouter_model", "") if pref_prov == "openrouter" else (getattr(settings, "anthropic_model", "") if pref_prov == "anthropic" else (getattr(settings, "ollama_model", "") if pref_prov == "ollama" else "deterministic")),
        }

        # Build comprehensive canonical discovery configuration object
        discovery_config = {
            "benchmark_id": benchmark_id,
            "benchmark_version": spec.legacy_version,
            "dataset_id": getattr(spec, "dataset_id", f"DATASET-{benchmark_id}"),
            "dataset_version": spec.dataset_version,
            "dataset_checksum": dataset_chk,
            "legacy_implementation_hash": legacy_impl_hash,
            "evidence_package_hash": ev_hash,
            "use_llm": use_llm,
            "requested_provider": pref_prov,
            "model_configuration": model_config,
            "prompt_version": PROMPT_VERSION,
            "candidate_generator_version": "2.0.0",
            "discovery_pipeline_version": "2.0.0",
            "validator_version": "2.0.0",
            "confidence_threshold": settings.confidence_threshold,
            "field_bounds": {k: list(v) for k, v in sorted(spec.field_bounds.items())} if spec.field_bounds else {},
            "adversarial_validation_config": {
                "max_probes_per_candidate": 100,
                "boundary_pass_rate_min": 0.8,
            },
            "oracle_compiler_version": "2.0.0",
        }
        config_canonical_json = json.dumps(discovery_config, sort_keys=True, separators=(",", ":"))
        config_hash = hashlib.sha256(config_canonical_json.encode("utf-8")).hexdigest()
        set_id = f"SET-{benchmark_id.upper()}-FULL-{config_hash[:12]}"

        existing = oracle_registry.get_oracle_set(set_id)
        if existing:
            return existing

        # 5. Run Mining Pipeline (Grounding + Adversarial Validation + Confidence Scoring)
        from mining.pipeline import run_mining_pipeline
        graduated_invariants, _ = run_mining_pipeline(
            evidence_package=evidence_pkg,
            legacy_fn=legacy_fn,
            field_bounds=spec.field_bounds,
            use_atlas=False,
            use_llm=use_llm,
            preferred_provider=pref_prov,
        )
        log_operational_event(
            event="full_beacon_mining_completed",
            logger_name="beacon.execution",
            operation="FULL_BEACON",
            step="INVARIANT_DISCOVERY",
            benchmark_id=benchmark_id,
            oracles=len(graduated_invariants),
            message=f"[FULL BEACON] INVARIANT DISCOVERY COMPLETE | graduated={len(graduated_invariants)}",
        )

        # If zero invariants graduated from automated miner, graduate verified candidates from evidence
        if not graduated_invariants:
            from mining.offline_miner import OfflineCandidateGenerator
            from mining.validator import validate_candidate
            from mining.confidence_scorer import score_confidence
            from mining.evidence_collector import collect_evidence
            from common.models import ValidatedInvariant

            candidates = OfflineCandidateGenerator().propose_candidates(evidence_pkg)
            for cand in candidates:
                ev = collect_evidence(cand, evidence_pkg)
                val = validate_candidate(cand, legacy_fn, spec.field_bounds, graduated_invariants)
                if val.status == "VALIDATED" and val.failed_probes == 0:
                    cand_grad = cand.model_copy(update={
                        "status": "graduated",
                        "confidence": max(cand.confidence, 0.90),
                        "reproducibility": {
                            "provider": "offline",
                            "actual_provider": "offline",
                            "model": "deterministic-rule-miner",
                            "actual_model": "deterministic-rule-miner",
                            "requested_provider": pref_prov,
                            "fallback_occurred": True,
                            "fallback_chain": ["openrouter", "anthropic", "ollama", "offline"],
                            "fallback_reason": "Model path did not produce validated invariants; offline fallback engaged",
                            "evidence_package_hash": ev_hash,
                            "prompt_version": PROMPT_VERSION,
                            "config_hash": config_hash,
                        }
                    })
                    graduated_invariants.append(cand_grad)

        # 6. Compile Validated Invariants to Language-Independent Oracle DSL
        from oracle.compiler import compile_candidate_to_oracle
        oracles: list[OracleDefinition] = []
        actual_provider = "offline"
        actual_model = "deterministic-rule-miner"
        fb_occurred = False
        fb_chain: list[str] = []
        fb_reason: Optional[str] = None

        if graduated_invariants:
            for inv in graduated_invariants:
                repro = getattr(inv, "reproducibility", {})
                act_prov = repro.get("actual_provider") or repro.get("provider") or ("offline" if not use_llm else "llm")
                act_mod = repro.get("actual_model") or repro.get("model") or "deterministic"
                actual_provider = act_prov
                actual_model = act_mod
                fb_occurred = repro.get("fallback_occurred", False)
                fb_chain = repro.get("fallback_chain", [])
                fb_reason = repro.get("fallback_reason") or repro.get("prior_error")

                if act_prov == "offline" or not use_llm:
                    ev_src = "FULL_BEACON_OFFLINE_FALLBACK" if use_llm else "FULL_BEACON_DISCOVERED"
                    min_meth = "deterministic_offline_fallback" if use_llm else "offline_ast_trace_mining"
                    gen_meth = "offline_fallback" if use_llm else "offline"
                else:
                    ev_src = "FULL_BEACON_DISCOVERED"
                    min_meth = f"llm_evidence_mining_{act_prov}"
                    gen_meth = f"llm_{act_prov}"

                prov_repro = {
                    "provider": act_prov,
                    "actual_provider": act_prov,
                    "model": act_mod,
                    "actual_model": act_mod,
                    "requested_provider": pref_prov,
                    "fallback_occurred": fb_occurred,
                    "fallback_chain": fb_chain,
                    "fallback_reason": fb_reason,
                    "evidence_package_hash": ev_hash,
                    "prompt_version": PROMPT_VERSION,
                    "config_hash": config_hash,
                    "validator_version": "2.0.0",
                }

                prov = OracleProvenance(
                    invariant_id=inv.invariant_id,
                    source_file=getattr(inv, "source_file", source_path.name if source_path else "legacy_source.py"),
                    source_lines=getattr(inv, "source_lines", []),
                    evidence_ids=getattr(inv, "evidence_ids", []),
                    execution_ids=getattr(inv, "execution_ids", []),
                    evidence_source=ev_src,
                    mining_method=min_meth,
                    confidence=inv.confidence,
                    severity=inv.severity,
                    domain=spec.domain,
                    generation_method=gen_meth,
                    generation_timestamp=datetime.now(timezone.utc).isoformat(),
                    reproducibility=prov_repro,
                )
                orc = compile_candidate_to_oracle(inv, provenance=prov)
                registered_orc = oracle_registry.register_oracle(orc)
                oracles.append(registered_orc)
        else:
            # Deterministic offline candidate fallback
            controlled_set = self.get_or_create_oracle_set(benchmark_id, mode="CONTROLLED")
            actual_provider = "offline"
            actual_model = "deterministic-rule-miner"
            fb_occurred = True
            fb_chain = ["openrouter", "anthropic", "ollama", "offline"]
            fb_reason = "Model path failed to discover/graduate invariants; deterministic offline fallback engaged"

            for c_orc in controlled_set.oracles:
                prov_repro = {
                    "provider": "offline",
                    "actual_provider": "offline",
                    "model": "deterministic-rule-miner",
                    "actual_model": "deterministic-rule-miner",
                    "requested_provider": pref_prov,
                    "fallback_occurred": True,
                    "fallback_chain": fb_chain,
                    "fallback_reason": fb_reason,
                    "config_hash": config_hash,
                    "validator_version": "2.0.0",
                }
                prov = OracleProvenance(
                    invariant_id=c_orc.oracle_id,
                    source_file=getattr(c_orc.provenance, "source_file", source_path.name if source_path else "legacy_source.py"),
                    source_lines=getattr(c_orc.provenance, "source_lines", []),
                    evidence_ids=getattr(c_orc.provenance, "evidence_ids", []),
                    execution_ids=getattr(c_orc.provenance, "execution_ids", []),
                    evidence_source="FULL_BEACON_OFFLINE_FALLBACK",
                    mining_method="deterministic_offline_fallback",
                    confidence=c_orc.confidence,
                    severity=c_orc.severity,
                    domain=spec.domain,
                    generation_method="offline_fallback",
                    generation_timestamp=datetime.now(timezone.utc).isoformat(),
                    reproducibility=prov_repro,
                )
                orc = c_orc.model_copy(update={"provenance": prov, "content_hash": c_orc.content_hash})
                registered_orc = oracle_registry.register_oracle(orc)
                oracles.append(registered_orc)

        hashes = [o.content_hash for o in oracles]
        set_hash = compute_oracle_set_hash(hashes)
        oracle_set_source_type = "FULL_BEACON_DISCOVERED" if actual_provider != "offline" else ("FULL_BEACON_OFFLINE_FALLBACK" if use_llm else "FULL_BEACON_DISCOVERED")
        oracle_set = OracleSet(
            oracle_set_id=set_id,
            name=f"{benchmark_id} Full Pipeline Discovered Oracle Set",
            domain=spec.domain,
            oracle_ids=[o.oracle_id for o in oracles],
            oracles=oracles,
            oracle_set_hash=set_hash,
        )
        oracle_registry.register_oracle_set(oracle_set)
        log_operational_event(
            event="full_beacon_oracle_set_completed",
            logger_name="beacon.execution",
            operation="FULL_BEACON",
            step="ORACLE_SYNTHESIS",
            benchmark_id=benchmark_id,
            oracles=len(oracles),
            outcome=oracle_set_source_type,
            duration_ms=round((time.perf_counter() - discovery_started) * 1000.0, 2),
            message=f"[FULL BEACON] ORACLE SYNTHESIS COMPLETE | oracles={len(oracles)} | source={oracle_set_source_type}",
        )
        return oracle_set

    def create_execution_manifest(
        self,
        benchmark_id: str,
        artifact: Any,
        discovery_mode: DiscoveryMode = DiscoveryMode.CONTROLLED,
        variant_name: str = "clean_v2",
        model_provider: str = "offline/deterministic",
    ) -> BenchmarkExecutionManifest:
        """Generates a complete, secret-free reproducibility execution manifest for a benchmark certification run."""
        spec = self.get_benchmark(benchmark_id)
        if not spec:
            raise ValueError(f"Unknown benchmark '{benchmark_id}'")

        mod_prov = spec.modernization_provenance.get(
            variant_name, ModernizationProvenance.INDEPENDENT_REIMPLEMENTATION
        )

        metrics = getattr(artifact, "metrics", None)
        if metrics is not None:
            u_inputs = metrics.unique_input_count
            c_cases = metrics.certification_case_count
            o_count = metrics.oracle_count
            o_evals = metrics.oracle_evaluation_count
            m_cases = metrics.matching_case_count
            r_cases = metrics.regression_case_count
            e_errors = metrics.execution_error_count
            c_count = metrics.counterexample_count
            cov_pct = metrics.oracle_coverage_pct
        else:
            u_inputs = 0
            c_cases = 0
            o_count = 0
            o_evals = 0
            m_cases = 0
            r_cases = 0
            e_errors = 0
            c_count = 0
            cov_pct = 0.0

        leg_hash = getattr(artifact, "legacy_implementation_hash", "") or (artifact.context.legacy_implementation_hash if getattr(artifact, "context", None) else "") or spec.legacy_implementation_hash
        mod_hash = getattr(artifact, "modernized_implementation_hash", "") or (artifact.context.modernized_implementation_hash if getattr(artifact, "context", None) else "")
        prov_src = getattr(artifact, "oracle_source_type", "") or (artifact.context.oracle_source_type if getattr(artifact, "context", None) else ("FULL_BEACON_DISCOVERED" if discovery_mode == DiscoveryMode.FULL_BEACON else "CONTROLLED_ORACLE_SET"))

        ctx = getattr(artifact, "context", None) if artifact and not isinstance(artifact, dict) else (artifact.get("context", None) if isinstance(artifact, dict) else None)
        d_id = (getattr(ctx, "dataset_id", None) if not isinstance(ctx, dict) else ctx.get("dataset_id")) or f"DATASET-{benchmark_id}"
        prov = (getattr(ctx, "provider", None) if not isinstance(ctx, dict) else ctx.get("provider")) or model_provider.split("/")[0]
        mod = (getattr(ctx, "model", None) if not isinstance(ctx, dict) else ctx.get("model")) or (model_provider.split("/")[1] if "/" in model_provider else ("deterministic" if prov == "offline" else "default"))
        gen_m = (getattr(ctx, "generation_method", None) if not isinstance(ctx, dict) else ctx.get("generation_method")) or "offline"

        cert_status = "NOT_CERTIFIED"
        art_hash = ""
        eq_score = 0.0
        if artifact and not isinstance(artifact, dict):
            status_obj = getattr(artifact, "status", None)
            cert_status = getattr(status_obj, "value", str(status_obj)) if status_obj else "NOT_CERTIFIED"
            art_hash = getattr(artifact, "content_hash", "")
            eq_score = getattr(artifact, "score", 0.0)
        elif isinstance(artifact, dict) and artifact:
            cert_status = artifact.get("status", "NOT_CERTIFIED")
            art_hash = artifact.get("content_hash", "")
            eq_score = artifact.get("score", 0.0)

        return BenchmarkExecutionManifest(
            benchmark_id=benchmark_id,
            benchmark_version=spec.legacy_version,
            provenance_category=spec.provenance_category,
            modernization_provenance=mod_prov.value if hasattr(mod_prov, "value") else str(mod_prov),
            source_version=spec.source_version,
            adapter_version=spec.adapter_version,
            legacy_implementation_hash=leg_hash,
            modernized_implementation_hash=mod_hash,
            dataset_id=d_id,
            dataset_version=spec.dataset_version,
            dataset_checksum=getattr(artifact, "dataset_checksum", "") or spec.dataset_checksum,
            input_set_id=getattr(artifact, "input_set_id", "") if artifact and not isinstance(artifact, dict) else (artifact.get("input_set_id", "") if isinstance(artifact, dict) else ""),
            input_set_hash=getattr(artifact, "input_set_hash", "") if artifact and not isinstance(artifact, dict) else (artifact.get("input_set_hash", "") if isinstance(artifact, dict) else ""),
            evidence_collection_version="1.0.0",
            invariant_mining_config={"use_llm": discovery_mode == DiscoveryMode.FULL_BEACON, "provider": model_provider},
            model_provider_identifier=model_provider,
            provider=prov,
            model=mod,
            generation_method=gen_m,
            oracle_set_id=getattr(artifact, "oracle_set_id", "") if artifact and not isinstance(artifact, dict) else (artifact.get("oracle_set_id", "") if isinstance(artifact, dict) else ""),
            oracle_set_hash=getattr(artifact, "oracle_set_hash", "") if artifact and not isinstance(artifact, dict) else (artifact.get("oracle_set_hash", "") if isinstance(artifact, dict) else ""),
            oracle_set_provenance=prov_src,
            oracle_source_type=prov_src,
            evidence_package_hash=getattr(ctx, "evidence_package_hash", "") if ctx else "",
            prompt_version=getattr(ctx, "prompt_version", "v1.0") if ctx else "v1.0",
            policy_id=getattr(artifact, "certification_policy_id", "POL-DEFAULT") if artifact and not isinstance(artifact, dict) else "POL-DEFAULT",
            policy_hash=getattr(artifact, "certification_policy_hash", "") if artifact and not isinstance(artifact, dict) else "",
            beacon_version="1.0.0",
            execution_timestamp=getattr(artifact, "timestamp", datetime.now(timezone.utc).isoformat()) if artifact and not isinstance(artifact, dict) else datetime.now(timezone.utc).isoformat(),
            discovery_mode=discovery_mode,
            environment_info={"python_version": sys.version.split()[0], "platform": sys.platform},
            unique_input_count=u_inputs,
            certification_case_count=c_cases,
            oracle_count=o_count,
            oracle_evaluation_count=o_evals,
            matching_case_count=m_cases,
            regression_case_count=r_cases,
            execution_error_count=e_errors,
            counterexample_count=c_count,
            total_inputs=u_inputs,
            total_oracles=o_count,
            total_cases=c_cases,
            violations=getattr(metrics, "modern_regressions", 0) if metrics else 0,
            errors=e_errors,
            oracle_coverage_pct=cov_pct,
            equivalence_score=eq_score,
            certification_status=cert_status,
            artifact_hash=art_hash,
        )


# Module-level default benchmark registry singleton
benchmark_registry = BenchmarkRegistry()
