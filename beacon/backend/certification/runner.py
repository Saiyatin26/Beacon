"""Stage 4 / Phase 9 — Cross-Version Certification Runner.

Wraps legacy and modernized implementations in adapters, runs the Phase-9
CrossVersionCertificationEngine, and produces both the new CrossVersionCertificationReport
and backward-compatible CertificationRun contracts.
"""

from datetime import datetime, timezone
from typing import Callable, Optional, Union
import uuid

from common.models import CertificationRun, Oracle, Violation
from oracle.models import OracleDefinition
from .adapters import LegacyAdapter, ModernizedAdapter
from .engine import certification_engine
from .models import CrossVersionCertificationReport


def certify(
    oracles: list[Union[Oracle, OracleDefinition]],
    modern_fn: Callable[..., dict],
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    domain_of: Optional[dict[str, str]] = None,
    n_samples: int = 100,
    seed: int = 42,
) -> CertificationRun:
    """Certifies a candidate modernized implementation against legacy reference
    using the language-independent Phase-9 certification engine.
    """
    legacy_adapter = LegacyAdapter(target_fn=legacy_fn, name="legacy_reference", version="1.0.0")
    modern_adapter = ModernizedAdapter(target_fn=modern_fn, name="modernized_candidate", version="2.0.0")

    report: CrossVersionCertificationReport = certification_engine.certify_equivalence(
        oracles=oracles,
        legacy_adapter=legacy_adapter,
        modern_adapter=modern_adapter,
        field_bounds=field_bounds,
        domain_of=domain_of,
        n_samples=n_samples,
        seed=seed,
    )

    # Convert regressions into backward-compatible Violation objects
    oracles_by_id = {getattr(o, "oracle_id", getattr(o, "invariant_id", "")): o for o in oracles}
    oracles_by_inv_id = {getattr(o, "invariant_id", getattr(o, "oracle_id", "")): o for o in oracles}

    violations: list[Violation] = []
    for reg in report.regressions:
        orc = oracles_by_id.get(reg.oracle_id) or oracles_by_inv_id.get(reg.oracle_id)
        inv_id = getattr(orc, "invariant_id", reg.oracle_id) if orc else reg.oracle_id
        prop = getattr(orc, "property", "") if orc else ""
        if not prop and orc:
            prop = f"({getattr(orc, 'canonical_condition', '')}) implies (decision == '{getattr(orc, 'consequence', '')}')"
        if not prop:
            prop = str(reg.expected_behavior)

        violations.append(Violation(
            invariant_id=inv_id,
            expected=prop,
            legacy_output=str(reg.legacy_output),
            modern_output=str(reg.modern_output),
            counterexample=reg.input_values,
            confidence=reg.confidence,
            severity=reg.severity,
        ))

    return CertificationRun(
        run_id=report.certification_id.replace("RUN-", ""),
        timestamp=report.timestamp,
        equivalence_score=report.overall_equivalence_score,
        domain_scores=report.domain_scores,
        violations=violations,
        total_checked=report.total_applicable_probes,
        total_violated=report.total_regressions,
    )
