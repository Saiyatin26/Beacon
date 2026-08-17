import abc
from common.models import CandidateInvariant
from evidence.models import UnifiedEvidencePackage

class CandidateGenerator(abc.ABC):
    """Abstract interface for proposing invariant candidates from an evidence package."""
    
    @abc.abstractmethod
    def propose_candidates(self, evidence_package: UnifiedEvidencePackage) -> list[CandidateInvariant]:
        """Propose candidates based on the unified evidence."""
        pass
