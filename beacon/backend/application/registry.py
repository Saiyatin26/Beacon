"""BEACON V2 — Application Registry.

Maintains registered ApplicationSpec definitions independently of BenchmarkRegistry,
enabling direct certification of arbitrary enterprise applications without
pre-packaged benchmark dependencies.
"""

import logging
from typing import Optional

from .models import ApplicationSpec
from .repository import application_repository, ApplicationRepository

logger = logging.getLogger("beacon.application")


class ApplicationRegistry:
    """Registry for managing ApplicationSpec definitions."""

    def __init__(self, repository: Optional[ApplicationRepository] = None):
        self._repo = repository or application_repository

    def register_application(self, spec: ApplicationSpec) -> ApplicationSpec:
        """Registers and persists an ApplicationSpec."""
        logger.info(f"Registering ApplicationSpec '{spec.name}' (id={spec.application_id}, domain={spec.domain or 'none'})")
        return self._repo.save_application(spec)

    def get_application(self, application_id: str) -> Optional[ApplicationSpec]:
        """Resolves an ApplicationSpec by ID."""
        return self._repo.get_application(application_id)

    def list_applications(self, domain: Optional[str] = None) -> list[ApplicationSpec]:
        """Lists registered applications, optionally filtered by domain."""
        return self._repo.list_applications(domain=domain)

    def unregister_application(self, application_id: str) -> bool:
        """Removes an ApplicationSpec from the registry."""
        return self._repo.delete_application(application_id)

    def clear(self) -> None:
        """Clears all registered applications."""
        self._repo.clear()


# Default singleton instance
application_registry = ApplicationRegistry()
