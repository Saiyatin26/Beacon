"""BEACON V2 — Domain-Agnostic Application Specification & Models.

Establishes a domain-neutral representation for systems under certification,
strictly separating Application (the actual system under test) from
Benchmark (pre-packaged demonstration scenarios).
"""

from enum import Enum
import hashlib
import json
from typing import Any, Callable, Literal, Optional, Union
from pydantic import BaseModel, Field


class ApplicationRole(str, Enum):
    """Execution roles for implementation targets within an application."""
    REFERENCE = "reference"
    TARGET = "target"
    # Backward compatibility aliases
    LEGACY = "legacy"
    MODERNIZED = "modernized"


class ImplementationType(str, Enum):
    """Runtime implementation types supported or planned."""
    PYTHON_CALLABLE = "python_callable"
    SOURCE_FILE = "source_file"
    SOURCE_DIRECTORY = "source_directory"
    PACKAGE = "package"
    GIT_REPOSITORY = "git_repository"
    CONTAINER = "container"
    REST_ENDPOINT = "rest_endpoint"
    CLI_EXECUTABLE = "cli_executable"


class ImplementationTarget(BaseModel):
    """Generic description of an implementation target (reference or target candidate)."""
    model_config = {"arbitrary_types_allowed": True}

    target_id: str = ""
    name: str = "implementation"
    role: Union[ApplicationRole, str] = ApplicationRole.TARGET
    implementation_type: Union[ImplementationType, str] = ImplementationType.PYTHON_CALLABLE
    entrypoint: Union[str, Callable[..., Any], Any] = ""
    version: str = "1.0.0"
    source_hash: str = ""
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.target_id:
            object.__setattr__(self, "target_id", f"{self.name}_{self.version}_{self.role}")


class InputContract(BaseModel):
    """Contract defining schema and constraints for application inputs."""
    fields: dict[str, Any] = Field(default_factory=dict)
    schema_type: str = "json"
    constraints: dict[str, Any] = Field(default_factory=dict)
    allow_extra: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutputContract(BaseModel):
    """Contract defining schema, normalizer, and tolerances for application outputs."""
    fields: dict[str, Any] = Field(default_factory=dict)
    schema_type: str = "json"
    normalizer: Optional[str] = "preserve_case"
    tolerance: Optional[dict[str, float]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeConfig(BaseModel):
    """Runtime execution environment configuration."""
    language: str = "python"
    runtime_version: Optional[str] = None
    timeout_seconds: float = 30.0
    environment_variables: dict[str, str] = Field(default_factory=dict)
    working_directory: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetConfig(BaseModel):
    """Configuration for test dataset generation, loading, or sampling."""
    dataset_id: Optional[str] = None
    generator_type: str = "synthetic"
    sample_count: int = 100
    seed: int = 42
    dataset_path: Optional[str] = None
    input_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuleConfig(BaseModel):
    """Configuration for oracle rules, invariants, and rule sources."""
    mode: Literal["CONTROLLED", "USER_PROVIDED", "FULL_BEACON", "FULL_BEACON_DISCOVERED", "RECONCILED"] = "CONTROLLED"
    rule_sources: list[str] = Field(default_factory=lambda: ["user_provided"])
    oracle_set_id: Optional[str] = None
    rules: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceConfig(BaseModel):
    """Configuration for behavioral evidence collection during certification."""
    capture_inputs: bool = True
    capture_outputs: bool = True
    capture_exceptions: bool = True
    capture_traces: bool = False
    capture_state: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionConfig(BaseModel):
    """Execution strategy configuration (parallelism, timeouts, retries)."""
    parallel_workers: int = 1
    timeout_ms: float = 5000.0
    retry_count: int = 0
    fail_fast: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


def compute_application_spec_hash(spec_dict: dict[str, Any]) -> str:
    """Computes deterministic SHA-256 hash of an ApplicationSpec payload."""
    canonical = json.dumps(spec_dict, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApplicationSpec(BaseModel):
    """Canonical domain-neutral specification for an application under certification.
    
    The domain field is strictly optional metadata (for UI display, grouping,
    and reporting). Certification equivalence NEVER branches on domain logic.
    """
    model_config = {"arbitrary_types_allowed": True}

    application_id: str
    name: str
    description: Optional[str] = None
    domain: Optional[str] = None  # Metadata only: "agriculture", "healthcare", "banking", etc.
    version: str = "1.0.0"

    reference_implementation: Union[ImplementationTarget, str, dict[str, Any], Callable[..., Any], Any]
    target_implementations: list[Union[ImplementationTarget, str, dict[str, Any], Callable[..., Any], Any]] = Field(default_factory=list)

    input_contract: Optional[InputContract] = None
    output_contract: Optional[OutputContract] = None

    runtime: Optional[RuntimeConfig] = None
    dependencies: list[str] = Field(default_factory=list)

    dataset_config: Optional[DatasetConfig] = None
    rule_config: Optional[RuleConfig] = None
    evidence_config: Optional[EvidenceConfig] = None
    execution_config: Optional[ExecutionConfig] = None

    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    spec_hash: str = ""

    def get_reference_target(self) -> ImplementationTarget:
        """Helper to resolve reference implementation as ImplementationTarget."""
        if isinstance(self.reference_implementation, ImplementationTarget):
            return self.reference_implementation
        if isinstance(self.reference_implementation, dict):
            return ImplementationTarget(**self.reference_implementation)
        if callable(self.reference_implementation):
            return ImplementationTarget(
                target_id=f"{self.application_id}_reference",
                name=f"{self.name}_reference",
                role=ApplicationRole.REFERENCE,
                entrypoint=self.reference_implementation,
            )
        return ImplementationTarget(
            target_id=f"{self.application_id}_reference",
            name=f"{self.name}_reference",
            role=ApplicationRole.REFERENCE,
            entrypoint=str(self.reference_implementation),
        )

    def get_target_candidates(self) -> list[ImplementationTarget]:
        """Helper to resolve target implementations as list of ImplementationTarget."""
        targets = []
        for t in self.target_implementations:
            if isinstance(t, ImplementationTarget):
                targets.append(t)
            elif isinstance(t, dict):
                targets.append(ImplementationTarget(**t))
            elif callable(t):
                targets.append(
                    ImplementationTarget(
                        target_id=f"{self.application_id}_target_{len(targets)}",
                        name=f"{self.name}_target_{len(targets)}",
                        role=ApplicationRole.TARGET,
                        entrypoint=t,
                    )
                )
            else:
                targets.append(
                    ImplementationTarget(
                        target_id=f"{self.application_id}_target_{len(targets)}",
                        name=f"{self.name}_target_{len(targets)}",
                        role=ApplicationRole.TARGET,
                        entrypoint=str(t),
                    )
                )
        return targets

    def compute_spec_hash(self) -> str:
        """Computes and returns cryptographic hash of the specification."""
        dumped = self.model_dump(exclude={"spec_hash"}, mode="json") if hasattr(self, "model_dump") else {}
        return compute_application_spec_hash(dumped)


class RepositoryExecutionSpec(BaseModel):
    """Authoritative execution specification synthesized from real repository analysis."""
    model_config = {"arbitrary_types_allowed": True}

    specification_id: str = ""
    legacy_source_identity: dict[str, Any] = Field(default_factory=dict)
    modern_source_identity: dict[str, Any] = Field(default_factory=dict)
    legacy_adapter: dict[str, Any] = Field(default_factory=dict)
    modern_adapter: dict[str, Any] = Field(default_factory=dict)
    legacy_entrypoint: str = ""
    modern_entrypoint: str = ""
    discovered_rules: list[dict[str, Any]] = Field(default_factory=list)
    discovered_inputs: list[dict[str, Any]] = Field(default_factory=list)
    input_set_identity: str = ""
    rule_set_identity: str = ""
    evaluation_mode: str = "CONTROLLED"
    policy_identity: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    specification_fingerprint: str = ""
    creation_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_fingerprint(self) -> str:
        """Computes authoritative specification fingerprint binding sources, adapters, inputs, rules, and mode."""
        canonical_content = json.dumps({
            "legacy_source": self.legacy_source_identity,
            "modern_source": self.modern_source_identity,
            "legacy_adapter": self.legacy_adapter,
            "modern_adapter": self.modern_adapter,
            "legacy_entrypoint": self.legacy_entrypoint,
            "modern_entrypoint": self.modern_entrypoint,
            "input_set_identity": self.input_set_identity or hashlib.sha256(json.dumps(self.discovered_inputs, sort_keys=True).encode()).hexdigest(),
            "rule_set_identity": self.rule_set_identity or hashlib.sha256(json.dumps(self.discovered_rules, sort_keys=True).encode()).hexdigest(),
            "evaluation_mode": self.evaluation_mode,
            "policy_identity": self.policy_identity,
        }, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()

    def model_post_init(self, __context: Any) -> None:
        if not self.input_set_identity and self.discovered_inputs:
            object.__setattr__(
                self,
                "input_set_identity",
                hashlib.sha256(json.dumps(self.discovered_inputs, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest(),
            )
        if not self.rule_set_identity and self.discovered_rules:
            object.__setattr__(
                self,
                "rule_set_identity",
                hashlib.sha256(json.dumps(self.discovered_rules, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest(),
            )
        if not self.specification_fingerprint:
            object.__setattr__(self, "specification_fingerprint", self.compute_fingerprint())


def build_application_spec_from_repository_execution_spec(
    repo_spec: RepositoryExecutionSpec,
) -> ApplicationSpec:
    """Deterministically bridges an authoritative RepositoryExecutionSpec into the internal ApplicationSpec model.
    
    Preserves specification fingerprint, source provenance, input set identity, and immutable adapter bindings.
    """
    app_id = repo_spec.specification_id or f"repo_{repo_spec.specification_fingerprint[:16]}"
    
    legacy_adapter_meta = repo_spec.legacy_adapter or {}
    modern_adapter_meta = repo_spec.modern_adapter or {}

    ref_target = ImplementationTarget(
        name=legacy_adapter_meta.get("adapter_name") or legacy_adapter_meta.get("adapter_id") or "legacy_ref",
        version=repo_spec.legacy_source_identity.get("commit_sha", "1.0.0")[:12],
        target_type="adapter",
        entrypoint=repo_spec.legacy_entrypoint or "reference",
        role=ApplicationRole.REFERENCE,
        source_hash=repo_spec.legacy_source_identity.get("content_hash", ""),
        metadata={
            "provenance": repo_spec.legacy_source_identity,
            "adapter_resolution": legacy_adapter_meta,
        },
    )

    modern_target = ImplementationTarget(
        name=modern_adapter_meta.get("adapter_name") or modern_adapter_meta.get("adapter_id") or "modern_tgt",
        version=repo_spec.modern_source_identity.get("commit_sha", "1.0.0")[:12],
        target_type="adapter",
        entrypoint=repo_spec.modern_entrypoint or "target",
        role=ApplicationRole.TARGET,
        source_hash=repo_spec.modern_source_identity.get("content_hash", ""),
        metadata={
            "provenance": repo_spec.modern_source_identity,
            "adapter_resolution": modern_adapter_meta,
        },
    )

    rule_mode = "CONTROLLED" if repo_spec.evaluation_mode == "CONTROLLED" else "FULL_BEACON"
    
    spec = ApplicationSpec(
        application_id=app_id,
        name=f"Repo-Certification-{app_id}",
        version="1.0.0",
        domain="general",
        reference_implementation=ref_target,
        target_implementations=[modern_target],
        rule_config=RuleConfig(mode=rule_mode),
        dataset_config=DatasetConfig(
            metadata={
                "custom_inputs": repo_spec.discovered_inputs,
                "input_set_identity": repo_spec.input_set_identity,
            }
        ),
        metadata={
            "specification_id": repo_spec.specification_id,
            "specification_fingerprint": repo_spec.specification_fingerprint,
            "legacy_provenance": repo_spec.legacy_source_identity,
            "modern_provenance": repo_spec.modern_source_identity,
            "legacy_adapter": legacy_adapter_meta,
            "modern_adapter": modern_adapter_meta,
            "input_set_identity": repo_spec.input_set_identity,
            "rule_set_identity": repo_spec.rule_set_identity,
            "evaluation_mode": repo_spec.evaluation_mode,
            "policy_identity": repo_spec.policy_identity,
            "discovered_rules": repo_spec.discovered_rules,
            "discovered_inputs_count": len(repo_spec.discovered_inputs),
            "creation_timestamp": repo_spec.creation_timestamp,
        },
    )
    return spec

