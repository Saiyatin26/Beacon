"""BEACON V2 — Application Resolver.

Resolves an ApplicationSpec into executable Reference and Target ImplementationAdapters,
canonical test input sets, and OracleSets without hardcoding any business domain logic.
"""

import importlib
import logging
from pathlib import Path
from typing import Any, Callable, Optional, Union

from common.contracts import (
    AdapterRole,
    CanonicalInput,
    ImplementationAdapter,
    adapter_registry,
)
from certification.adapters import (
    ConfiguredOutputNormalizer,
    DefaultOutputNormalizer,
    FunctionAdapter,
    PreserveCaseNormalizer,
    ReferenceAdapter,
    StripWhitespaceNormalizer,
    TargetAdapter,
)
from certification.models import CertificationTestInput
from oracle.models import OracleDefinition, OracleRule, OracleSet, OracleSourceMode, RuleSeverity
from oracle.registry import registry as oracle_registry
from .models import ApplicationSpec, ImplementationTarget

logger = logging.getLogger("beacon.application.resolver")


class ApplicationResolutionError(ValueError):
    """Raised when an ApplicationSpec cannot be resolved to valid runtime components."""
    pass


class ApplicationResolver:
    """Resolves ApplicationSpec models into runtime certification components."""

    @staticmethod
    def _create_normalizer(normalizer_name: Optional[str]):
        """Builds an OutputNormalizer from contract name."""
        if not normalizer_name or normalizer_name == "preserve_case":
            return PreserveCaseNormalizer()
        elif normalizer_name == "strip_whitespace":
            return StripWhitespaceNormalizer()
        elif normalizer_name == "uppercase" or normalizer_name == "default":
            return DefaultOutputNormalizer()
        return PreserveCaseNormalizer()

    def resolve_target_to_adapter(
        self,
        target: Union[ImplementationTarget, str, dict[str, Any], Callable[..., Any]],
        role: str = "target",
        normalizer_name: Optional[str] = None,
    ) -> ImplementationAdapter:
        """Resolves a target definition into an executable ImplementationAdapter."""
        output_norm = self._create_normalizer(normalizer_name)

        # 1. Directly passed callable
        if callable(target):
            if isinstance(target, type) and issubclass(target, ImplementationAdapter):
                inst = target()
                inst.role = role
                return inst
            name = getattr(target, "__name__", f"callable_{role}")
            if role in (AdapterRole.REFERENCE, "reference", "legacy"):
                return ReferenceAdapter(target_fn=target, name=name, output_normalizer=output_norm)
            return TargetAdapter(target_fn=target, name=name, output_normalizer=output_norm)

        # 2. String identifier (check adapter registry or dynamic import)
        if isinstance(target, str):
            # Check registry first
            registered = adapter_registry.get_adapter(target)
            if registered:
                return registered

            # Check if string is a python import path "module.path:fn_name"
            if ":" in target:
                mod_name, fn_name = target.split(":", 1)
                try:
                    mod = importlib.import_module(mod_name)
                    fn = getattr(mod, fn_name)
                    if isinstance(fn, type) and issubclass(fn, ImplementationAdapter):
                        inst = fn()
                        inst.role = role
                        return inst
                    elif callable(fn):
                        return FunctionAdapter(
                            target_fn=fn,
                            name=f"{mod_name}.{fn_name}",
                            role=role,
                            output_normalizer=output_norm,
                        )
                except Exception as exc:
                    raise ApplicationResolutionError(f"Could not import target function '{target}': {exc}")

            raise ApplicationResolutionError(f"Could not resolve adapter target identifier: '{target}'")

        # 3. ImplementationTarget or dict
        if isinstance(target, dict):
            target_obj = ImplementationTarget(**target)
        elif isinstance(target, ImplementationTarget):
            target_obj = target
        else:
            raise ApplicationResolutionError(f"Unsupported implementation target type: {type(target)}")

        # Try resolving entrypoint if available
        # 1. Check adapter registry by name first
        reg_adapter = adapter_registry.get_adapter(target_obj.name, version=target_obj.version)
        if reg_adapter:
            return reg_adapter

        if target_obj.entrypoint:
            if callable(target_obj.entrypoint):
                return FunctionAdapter(
                    target_fn=target_obj.entrypoint,
                    name=target_obj.name,
                    version=target_obj.version,
                    role=target_obj.role,
                    output_normalizer=output_norm,
                )
            elif isinstance(target_obj.entrypoint, str):
                registered_names = [a.name if hasattr(a, "name") else a["name"] for a in adapter_registry.list_adapters()]
                if target_obj.entrypoint in registered_names:
                    reg_adapter = adapter_registry.get_adapter(target_obj.entrypoint, version=target_obj.version)
                    if reg_adapter:
                        return reg_adapter
                if ":" in target_obj.entrypoint:
                    mod_name, fn_name = target_obj.entrypoint.split(":", 1)
                    try:
                        p = Path(mod_name)
                        if p.exists() or mod_name.endswith(".py"):
                            spec_imp = importlib.util.spec_from_file_location(p.stem, str(p.resolve()))
                            if spec_imp and spec_imp.loader:
                                mod = importlib.util.module_from_spec(spec_imp)
                                spec_imp.loader.exec_module(mod)
                            else:
                                mod = importlib.import_module(p.stem)
                        else:
                            mod = importlib.import_module(mod_name)
                        fn = getattr(mod, fn_name)
                        if isinstance(fn, type) and issubclass(fn, ImplementationAdapter):
                            inst = fn()
                            if hasattr(target_obj, "role") and target_obj.role:
                                inst.role = target_obj.role
                            return inst
                        elif callable(fn):
                            return FunctionAdapter(
                                target_fn=fn,
                                name=target_obj.name,
                                version=target_obj.version,
                                role=target_obj.role,
                                output_normalizer=output_norm,
                            )
                    except Exception as exc:
                        raise ApplicationResolutionError(f"Could not import entrypoint '{target_obj.entrypoint}': {exc}")

        raise ApplicationResolutionError(f"Cannot resolve implementation target '{target_obj.name}' to executable adapter")

    def resolve_adapters(
        self,
        spec: ApplicationSpec,
        target_index: int = 0,
    ) -> tuple[ImplementationAdapter, ImplementationAdapter]:
        """Resolves reference and candidate target adapters for an ApplicationSpec."""
        normalizer_name = spec.output_contract.normalizer if spec.output_contract else "preserve_case"

        # Reference
        ref_target = spec.get_reference_target()
        ref_adapter = self.resolve_target_to_adapter(
            target=ref_target,
            role=AdapterRole.REFERENCE,
            normalizer_name=normalizer_name,
        )

        # Target
        target_candidates = spec.get_target_candidates()
        if not target_candidates:
            raise ApplicationResolutionError(f"Application '{spec.name}' has no candidate target implementations")

        if target_index >= len(target_candidates):
            raise ApplicationResolutionError(
                f"Target index {target_index} out of bounds for application with {len(target_candidates)} targets"
            )

        target_adapter = self.resolve_target_to_adapter(
            target=target_candidates[target_index],
            role=AdapterRole.TARGET,
            normalizer_name=normalizer_name,
        )

        return ref_adapter, target_adapter

    def resolve_inputs(
        self,
        spec: ApplicationSpec,
        custom_inputs: Optional[list[Union[dict[str, Any], CanonicalInput, CertificationTestInput]]] = None,
        allow_synthetic_inputs: Optional[bool] = None,
    ) -> list[CertificationTestInput]:
        """Resolves or generates canonical test inputs for an ApplicationSpec.

        Input Resolution Architecture:
        1. Explicit custom_inputs or explicit Dataset configured?
           -> Load and validate dataset inputs.
           -> If dataset is missing or invalid, FAIL CLOSED. Never replace invalid dataset with synthetic inputs!
        2. Explicit InputContract with fields configured?
           -> Generate/validate inputs from InputContract.
           -> If generation fails, FAIL CLOSED. Never replace failed contract generation with synthetic inputs!
        3. No Dataset and No InputContract fields:
           -> Check if explicit TEST/DEVELOPMENT fallback is enabled (allow_synthetic_inputs=True).
           -> If NOT enabled (default is False), FAIL CLOSED: raise ApplicationResolutionError.
           -> If explicitly enabled, generate synthetic inputs with explicit provenance:
              source="phase2_test_development_fallback",
              mode="test_development_fallback_only",
              synthetic=True,
              explicitly_enabled=True.
        """
        import json

        # ----------------------------------------------------------------------
        # 1. Explicit Dataset Resolution
        # ----------------------------------------------------------------------
        # 1A. Custom inputs passed directly
        if custom_inputs is not None:
            if not isinstance(custom_inputs, list) or len(custom_inputs) == 0:
                raise ApplicationResolutionError("Custom inputs list cannot be empty.")
            inputs: list[CertificationTestInput] = []
            for i, item in enumerate(custom_inputs):
                if isinstance(item, CertificationTestInput):
                    inputs.append(item)
                elif isinstance(item, CanonicalInput):
                    inputs.append(
                        CertificationTestInput(
                            input_id=item.input_id or f"in_{i:04d}",
                            values=item.get_data(),
                            provenance=item.provenance,
                            tags=item.tags,
                        )
                    )
                elif isinstance(item, dict):
                    inputs.append(
                        CertificationTestInput(
                            input_id=str(item.get("input_id", f"in_{i:04d}")),
                            values=item.get("values", item),
                            provenance={"source": "custom_inputs"},
                        )
                    )
                else:
                    raise ApplicationResolutionError(f"Unsupported custom input element type: {type(item)}")
            return inputs

        # 1B. Dataset from dataset_path (file on filesystem)
        dataset_path_str = (
            (spec.dataset_config.dataset_path if spec.dataset_config else None)
            or spec.metadata.get("dataset_path")
        )
        if dataset_path_str:
            p = Path(dataset_path_str)
            if not p.exists():
                raise ApplicationResolutionError(
                    f"Configured dataset_path does not exist: '{dataset_path_str}'"
                )
            try:
                if p.suffix.lower() == ".json":
                    with open(p, "r", encoding="utf-8") as f:
                        records = json.load(f)
                    if not isinstance(records, list):
                        raise ValueError("JSON dataset root must be a list of records")
                elif p.suffix.lower() in (".jsonl", ".ndjson"):
                    records = []
                    with open(p, "r", encoding="utf-8") as f:
                        for line in f:
                            s = line.strip()
                            if s:
                                records.append(json.loads(s))
                elif p.suffix.lower() == ".csv":
                    import csv
                    with open(p, "r", encoding="utf-8") as f:
                        records = list(csv.DictReader(f))
                else:
                    content = p.read_text(encoding="utf-8")
                    try:
                        records = json.loads(content)
                    except Exception:
                        records = [json.loads(line) for line in content.splitlines() if line.strip()]

                if not records or not isinstance(records, list):
                    raise ValueError(f"Dataset file '{dataset_path_str}' contains no valid records")

                sample_count = (
                    spec.dataset_config.sample_count
                    if spec.dataset_config and spec.dataset_config.sample_count
                    else len(records)
                )
                selected = records[:sample_count]
                return [
                    CertificationTestInput(
                        input_id=f"ds_{i:04d}",
                        values=rec.get("values", rec) if isinstance(rec, dict) else {"value": rec},
                        provenance={"source": "explicit_dataset_path", "dataset_path": str(p)},
                    )
                    for i, rec in enumerate(selected)
                ]
            except Exception as exc:
                # FAIL CLOSED: Do NOT silently replace failed dataset loading with synthetic inputs!
                raise ApplicationResolutionError(f"Failed to load dataset from '{dataset_path_str}': {exc}")

        # 1C. Dataset from dataset_id (registered in user_dataset_registry)
        dataset_id = (
            (getattr(spec.dataset_config, "dataset_id", None) if spec.dataset_config else None)
            or spec.metadata.get("dataset_id")
        )
        if dataset_id:
            try:
                from ingestion.dataset_registry import user_dataset_registry
                reg_inputs = user_dataset_registry.get_test_inputs(dataset_id)
                if not reg_inputs:
                    raise ValueError(f"No test inputs found for dataset_id '{dataset_id}' in registry")
                sample_count = (
                    spec.dataset_config.sample_count
                    if spec.dataset_config and spec.dataset_config.sample_count
                    else len(reg_inputs)
                )
                return reg_inputs[:sample_count]
            except Exception as exc:
                # FAIL CLOSED: Do NOT silently replace missing registered dataset with synthetic inputs!
                raise ApplicationResolutionError(f"Failed to resolve dataset_id '{dataset_id}': {exc}")

        # 1D. Inline dataset records
        inline_records = (
            (spec.dataset_config.metadata.get("records") if spec.dataset_config else None)
            or spec.metadata.get("dataset_records")
        )
        if inline_records:
            if not isinstance(inline_records, list) or len(inline_records) == 0:
                raise ApplicationResolutionError("Inline dataset records must be a non-empty list.")
            return [
                CertificationTestInput(
                    input_id=f"rec_{i:04d}",
                    values=rec.get("values", rec) if isinstance(rec, dict) else {"value": rec},
                    provenance={"source": "explicit_dataset_records"},
                )
                for i, rec in enumerate(inline_records)
            ]

        # ----------------------------------------------------------------------
        # 2. Explicit InputContract Generation
        # ----------------------------------------------------------------------
        if spec.input_contract and spec.input_contract.fields:
            try:
                import random
                rng = random.Random(spec.dataset_config.seed if spec.dataset_config else 42)
                sample_count = spec.dataset_config.sample_count if spec.dataset_config else 50
                generated: list[CertificationTestInput] = []

                for i in range(sample_count):
                    vals: dict[str, Any] = {}
                    for field_name, field_def in spec.input_contract.fields.items():
                        if isinstance(field_def, dict):
                            f_type = field_def.get("type", "float")
                            f_min = field_def.get("min", 0)
                            f_max = field_def.get("max", 100)
                            if f_type in ("int", "integer"):
                                vals[field_name] = rng.randint(int(f_min), int(f_max))
                            elif f_type in ("float", "number"):
                                vals[field_name] = round(rng.uniform(float(f_min), float(f_max)), 2)
                            elif f_type in ("str", "string"):
                                options = field_def.get("enum", ["A", "B", "C"])
                                vals[field_name] = rng.choice(options)
                            elif f_type in ("bool", "boolean"):
                                vals[field_name] = rng.choice([True, False])
                            else:
                                vals[field_name] = rng.randint(0, 100)
                        elif isinstance(field_def, tuple) and len(field_def) == 2:
                            min_v, max_v = field_def
                            if isinstance(min_v, int) and isinstance(max_v, int):
                                vals[field_name] = rng.randint(min_v, max_v)
                            else:
                                vals[field_name] = round(rng.uniform(float(min_v), float(max_v)), 2)
                        elif isinstance(field_def, (int, float)):
                            vals[field_name] = field_def
                        elif isinstance(field_def, str):
                            vals[field_name] = field_def
                        else:
                            vals[field_name] = 10.0

                    generated.append(
                        CertificationTestInput(
                            input_id=f"synth_{i:04d}",
                            values=vals,
                            origin="diverse_sampling",
                            provenance={"generator": "contract_synthesizer", "source": "input_contract"},
                        )
                    )
                return generated
            except Exception as exc:
                # FAIL CLOSED: Do NOT silently replace failed contract generation with synthetic fallback!
                raise ApplicationResolutionError(f"Failed to generate test inputs from InputContract: {exc}")

        # ----------------------------------------------------------------------
        # 3. No Dataset and No InputContract fields -> Check Explicit Test/Dev Fallback
        # ----------------------------------------------------------------------
        effective_allow_synthetic = allow_synthetic_inputs
        if effective_allow_synthetic is None:
            if "allow_synthetic_inputs" in spec.metadata:
                effective_allow_synthetic = bool(spec.metadata["allow_synthetic_inputs"])
            else:
                from common.config import settings
                if callable(getattr(settings, "get_allow_synthetic_inputs", None)):
                    effective_allow_synthetic = settings.get_allow_synthetic_inputs()
                else:
                    effective_allow_synthetic = getattr(settings, "allow_synthetic_inputs", False)

        if not effective_allow_synthetic:
            raise ApplicationResolutionError(
                f"ApplicationSpec '{spec.application_id}' has no valid input source: "
                "no explicit dataset was provided, no explicit InputContract fields were declared, "
                "and allow_synthetic_inputs is disabled (default). "
                "Real applications must provide an explicit dataset or InputContract in production."
            )

        # TEST / DEVELOPMENT ONLY Fallback (explicitly enabled):
        logger.warning(
            f"[INPUT_FALLBACK] TEST/DEVELOPMENT ONLY: ApplicationSpec '{spec.application_id}' "
            "has neither a registered dataset nor input_contract fields. allow_synthetic_inputs=True is explicitly set. "
            "Generating synthetic fallback test inputs."
        )
        sample_count = spec.dataset_config.sample_count if spec.dataset_config else 10
        return [
            CertificationTestInput(
                input_id=f"default_test_{i:04d}",
                values={"x": i * 1.5, "flag": True},
                origin="diverse_sampling",
                provenance={
                    "source": "phase2_test_development_fallback",
                    "mode": "test_development_fallback_only",
                    "synthetic": True,
                    "explicitly_enabled": True,
                    "generator": "default_fallback",
                    "warning": "TEST/DEVELOPMENT ONLY: Fabricated synthetic inputs because allow_synthetic_inputs=True. Not for production certification.",
                },
            )
            for i in range(sample_count)
        ]

    def resolve_oracle_set(self, spec: ApplicationSpec) -> OracleSet:
        """Resolves an OracleSet for an ApplicationSpec.
        
        Strictly generic and domain-neutral:
        1. Checks for explicit oracle_set_id in rule_config
        2. Compiles explicit user-provided rules from rule_config
        3. If no rules or OracleSet specified, returns a deferred empty OracleSet with explicit metadata.
           Never invents domain-specific or heuristic rules.
        """
        # 1. Check if oracle_set_id provided in rule_config
        if spec.rule_config and spec.rule_config.oracle_set_id:
            oset = oracle_registry.get_oracle_set(spec.rule_config.oracle_set_id)
            if oset:
                return oset

        # 2. Check if explicit rules provided in rule_config
        oracles: list[OracleDefinition] = []
        if spec.rule_config and spec.rule_config.rules:
            from common.models import CandidateInvariant
            from oracle.compiler import compile_candidate_to_oracle
            for idx, r in enumerate(spec.rule_config.rules):
                if isinstance(r, OracleDefinition):
                    oracles.append(r)
                elif isinstance(r, dict):
                    cond = r.get("condition") or r.get("expression") or "true"
                    conseq = r.get("consequence") or "decision == true"
                    if "->" in cond and not r.get("consequence"):
                        parts = cond.split("->", 1)
                        cond, conseq = parts[0].strip(), parts[1].strip()
                    candidate = CandidateInvariant(
                        invariant_id=r.get("rule_id", f"{spec.application_id}_inv_{idx:03d}"),
                        condition=cond,
                        consequence=conseq,
                        confidence=1.0,
                        severity=str(r.get("severity", "critical")).lower(),
                    )
                    try:
                        compiled = compile_candidate_to_oracle(candidate)
                        oracles.append(compiled)
                    except Exception as exc:
                        logger.warning(f"Could not compile rule #{idx} to oracle: {exc}")

        # If no explicit oracles, DO NOT invent any domain-specific rules.
        # Rule discovery is deferred to later Full BEACON phases.

        from oracle.serializer import compute_oracle_set_hash
        oracle_hashes = [o.content_hash for o in oracles]
        set_hash = compute_oracle_set_hash(oracle_hashes) if oracle_hashes else ""

        oset = OracleSet(
            oracle_set_id=f"oset_{spec.application_id}",
            name=f"OracleSet for {spec.name}",
            version=1,
            domain=spec.domain or "generic",
            benchmark_id=spec.application_id,
            source_mode=spec.rule_config.mode if spec.rule_config else OracleSourceMode.USER_PROVIDED,
            oracles=oracles,
            oracle_ids=[o.oracle_id for o in oracles],
            oracle_set_hash=set_hash,
            metadata={
                "application_id": spec.application_id,
                "mode": spec.rule_config.mode if spec.rule_config else "USER_PROVIDED",
                "rules_count": len(oracles),
                "rule_discovery_status": "deferred_to_full_beacon" if not oracles else "explicit_rules_loaded",
            },
        )
        oracle_registry.register_oracle_set(oset)
        return oset


application_resolver = ApplicationResolver()

__all__ = ["ApplicationResolver", "application_resolver", "ApplicationResolutionError"]

