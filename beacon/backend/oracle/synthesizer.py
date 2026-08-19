"""Stage 3 / Phase 8 — Oracle Synthesis & Compilation.

Compiles a ValidatedInvariant into a language-independent, executable OracleDefinition
and registers it in the immutable OracleRegistry.
"""

import logging
from common.models import ValidatedInvariant, CandidateInvariant
from .compiler import compile_candidate_to_oracle, OracleCompilationError
from .models import OracleDefinition, Oracle
from .registry import registry

logger = logging.getLogger(__name__)


def synthesize_oracle(invariant: ValidatedInvariant) -> OracleDefinition:
    """Compiles a validated invariant into a canonical language-independent Oracle
    and registers it in the default OracleRegistry.
    """
    oracle = compile_candidate_to_oracle(invariant)
    registered_oracle = registry.register_oracle(oracle)
    return registered_oracle
