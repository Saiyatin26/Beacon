"""Stage 2f — OpenSpec provenance.

Every graduated invariant becomes an OpenSpec change proposal, giving a
git-tracked, human-readable audit trail from raw evidence to enforced rule
(architecture doc Section 2, and the claim-drafting note in Section 8 —
OpenSpec is the *embodiment* of the 'auditable versioned specification
artifact' function, not the function itself).

This module only writes the proposal.md file; running `openspec` CLI commands
(apply/archive) is left to the developer workflow, matching how OpenSpec is
meant to be used interactively alongside AI coding tools.
"""

from pathlib import Path
from common.models import ValidatedInvariant, EvidenceReport, ValidationReport

OPENSPEC_CHANGES_DIR = Path(__file__).resolve().parents[2] / "openspec" / "changes"


def write_proposal(
    invariant: ValidatedInvariant,
    evidence: EvidenceReport,
    validation: ValidationReport,
) -> Path:
    change_dir = OPENSPEC_CHANGES_DIR / invariant.invariant_id
    change_dir.mkdir(parents=True, exist_ok=True)

    proposal = f"""# Invariant {invariant.invariant_id}

## Mined rule
condition: `{invariant.condition}`
consequence: `{invariant.consequence}`
severity: {invariant.severity}

## Why
Discovered via BEACON Stage 2 invariant mining (hybrid static/dynamic analysis
+ LLM reasoning). Confidence {invariant.confidence:.2f}, graduated to an
enforced oracle: {invariant.graduated}.

## Evidence
- corroborating traces (normalized): {evidence.evidence_count_norm:.2f}
- input diversity: {evidence.input_diversity:.2f}

## Validation
- boundary-probe pass rate: {validation.boundary_pass_rate:.2f}
- contradictions against existing invariants: {validation.contradiction_count}

## Next step
This proposal feeds Stage 3 (oracle synthesis) if graduated; see
backend/oracle/synthesizer.py.
"""
    (change_dir / "proposal.md").write_text(proposal)
    return change_dir / "proposal.md"
