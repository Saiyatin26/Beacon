"""BEACON V2 — Application Resolver.

Resolves an ApplicationSpec into executable Reference and Target ImplementationAdapters,
canonical test input sets, and OracleSets without hardcoding any business domain logic.
"""

import importlib
import logging
from pathlib import Path
from typing import Any, Callable, Optional, Union

from certification.adapters import (
    AdapterRole,
    ConfiguredOutputNormalizer,
    DefaultOutputNormalizer,
    FunctionAdapter,
    ImplementationAdapter,
    PreserveCaseNormalizer,
    ReferenceAdapter,
    StripWhitespaceNormalizer,
    TargetAdapter,
)
from certification.adapter_registry import adapter_registry
from certification.models import CanonicalInput, CertificationTestInput
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
                    if callable(fn):
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
                if target_obj.entrypoint in [a["name"] for a in adapter_registry.list_adapters()]:
                    reg_adapter = adapter_registry.get_adapter(target_obj.entrypoint, version=target_obj.version)
                    if reg_adapter:
                        return reg_adapter
                if ":" in target_obj.entrypoint:
                    mod_name, fn_name = target_obj.entrypoint.split(":", 1)
                    try:
                        mod = importlib.import_module(mod_name)
                        fn = getattr(mod, fn_name)
                        return FunctionAdapter(
                            target_fn=fn,
                            name=target_obj.name,
                            version=target_obj.version,
                            role=target_obj.role,
                            output_normalizer=output_norm,
                        )
                    except Exception as exc:
                        raise ApplicationResolutionError(f"Could not import entrypoint '{target_obj.entrypoint}': {exc}")

        # Check adapter registry by name
        reg_adapter = adapter_registry.get_adapter(target_obj.name, version=target_obj.version)
        if reg_adapter:
            return reg_adapter

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
    ) -> list[CertificationTestInput]:
        """Resolves or generates canonical test inputs for an ApplicationSpec."""
        if custom_inputs:
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
            return inputs

        # Generate inputs from input contract if available
        if spec.input_contract and spec.input_contract.fields:
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
                    else:
                        vals[field_name] = 10.0

                generated.append(
                    CertificationTestInput(
                        input_id=f"synth_{i:04d}",
                        values=vals,
                        origin="diverse_sampling",
                        provenance={"generator": "contract_synthesizer"},
                    )
                )
            return generated

        # Default fallback sample inputs
        return [
            CertificationTestInput(
                input_id=f"default_{i:04d}",
                values={"x": i * 1.5, "flag": True},
                origin="diverse_sampling",
                provenance={"generator": "default_fallback"},
            )
            for i in range(10)
        ]

    def resolve_oracle_set(self, spec: ApplicationSpec) -> OracleSet:
        """Resolves or synthesizes an OracleSet for an ApplicationSpec."""
        # 1. Check if oracle_set_id provided in rule_config
        if spec.rule_config and spec.rule_config.oracle_set_id:
            oset = oracle_registry.get_oracle_set(spec.rule_config.oracle_set_id)
            if oset:
                return oset

        # 2. Check if explicit rules provided in rule_config or synthesize from contract
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

        if not oracles:
            # Create a baseline equivalence oracle from input contract fields
            from common.models import CandidateInvariant
            from oracle.compiler import compile_candidate_to_oracle
            first_field = list(spec.input_contract.fields.keys())[0] if spec.input_contract and spec.input_contract.fields else "soil_moisture"
            candidate = CandidateInvariant(
                invariant_id=f"{spec.application_id}_inv_base",
                condition=f"{first_field} >= 0",
                consequence="decision != None",
                confidence=1.0,
                severity="critical",
            )
            try:
                compiled = compile_candidate_to_oracle(candidate)
                oracles.append(compiled)
            except Exception:
                pass

        from oracle.serializer import compute_oracle_set_hash
        oracle_hashes = [o.content_hash for o in oracles]
        set_hash = compute_oracle_set_hash(oracle_hashes) if oracle_hashes else ""

        oset = OracleSet(
            oracle_set_id=f"oset_{spec.application_id}",
            name=f"OracleSet for {spec.name}",
            version=1,
            domain=spec.domain or "default",
            benchmark_id=spec.application_id,
            source_mode=spec.rule_config.mode if spec.rule_config else OracleSourceMode.CONTROLLED,
            oracles=oracles,
            oracle_ids=[o.oracle_id for o in oracles],
            oracle_set_hash=set_hash,
            metadata={"application_id": spec.application_id, "mode": spec.rule_config.mode if spec.rule_config else "CONTROLLED"},
        )
        oracle_registry.register_oracle_set(oset)
        return oset
