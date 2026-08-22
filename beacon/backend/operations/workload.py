"""Workload and Resource Protection Subsystem for BEACON.

Enforces configurable resource boundaries across dataset sizes, record counts,
and concurrent certification workloads.
Rejects oversized workloads explicitly rather than silently truncating data.
"""

import threading
from typing import Optional
from common.config import settings
from .errors import ResourceLimitError
from .metrics import operational_metrics
from .logging_config import log_operational_event, get_logger

logger = get_logger("beacon.workload")


class WorkloadProtector:
    """Manages active job limits and validates payload / dataset sizes against configured safety thresholds."""

    def __init__(self):
        self._lock = threading.RLock()
        self._active_count: int = 0

    @property
    def max_dataset_size_bytes(self) -> int:
        return getattr(settings, "max_dataset_size_bytes", 10 * 1024 * 1024)  # 10 MB default

    @property
    def max_input_records(self) -> int:
        return getattr(settings, "max_input_records", 5000)  # 5,000 records default

    @property
    def max_concurrent_jobs(self) -> int:
        return getattr(settings, "max_concurrent_jobs", 10)

    def validate_dataset_upload(self, raw_bytes_length: int, declared_records_count: Optional[int] = None) -> None:
        """Validates uploaded raw content against dataset limits."""
        if raw_bytes_length > self.max_dataset_size_bytes:
            msg = (
                f"Dataset payload size ({raw_bytes_length} bytes) exceeds maximum configured limit "
                f"of {self.max_dataset_size_bytes} bytes ({self.max_dataset_size_bytes // (1024 * 1024)} MB). "
                f"Ingestion rejected without truncation."
            )
            logger.warning(f"Workload violation: {msg}")
            log_operational_event(
                event="workload_limit_exceeded",
                error_category="RESOURCE_LIMIT",
                message=msg,
                details={"size_bytes": raw_bytes_length, "max_bytes": self.max_dataset_size_bytes},
            )
            raise ResourceLimitError(msg, details={"size_bytes": raw_bytes_length, "max_bytes": self.max_dataset_size_bytes})

        if declared_records_count is not None and declared_records_count > self.max_input_records:
            msg = (
                f"Dataset record count ({declared_records_count}) exceeds maximum configured limit "
                f"of {self.max_input_records} records. Ingestion rejected without truncation."
            )
            logger.warning(f"Workload violation: {msg}")
            log_operational_event(
                event="workload_limit_exceeded",
                error_category="RESOURCE_LIMIT",
                message=msg,
                details={"records": declared_records_count, "max_records": self.max_input_records},
            )
            raise ResourceLimitError(msg, details={"records": declared_records_count, "max_records": self.max_input_records})

    def validate_certification_records(self, record_count: int, project_id: Optional[str] = None) -> None:
        """Validates test input set record count before launching certification."""
        if record_count > self.max_input_records:
            msg = (
                f"Certification input count ({record_count}) exceeds maximum configured limit "
                f"of {self.max_input_records} inputs. Run rejected without truncation."
            )
            logger.warning(f"Workload limit exceeded for project '{project_id}': {msg}")
            log_operational_event(
                event="workload_limit_exceeded",
                project_id=project_id,
                error_category="RESOURCE_LIMIT",
                message=msg,
                details={"record_count": record_count, "max_input_records": self.max_input_records},
            )
            raise ResourceLimitError(msg, details={"record_count": record_count, "max_input_records": self.max_input_records})

    def acquire_job_slot(self, project_id: Optional[str] = None) -> None:
        """Attempts to acquire a slot for a concurrent certification job."""
        with self._lock:
            if self._active_count >= self.max_concurrent_jobs:
                msg = (
                    f"Maximum concurrent certification jobs limit ({self.max_concurrent_jobs}) reached. "
                    f"Please retry when active jobs complete."
                )
                logger.warning(f"Concurrency limit reached: {msg}")
                raise ResourceLimitError(msg, details={"active_jobs": self._active_count, "max_jobs": self.max_concurrent_jobs})

            self._active_count += 1
            operational_metrics.record_job_started()

    def release_job_slot(self) -> None:
        """Releases an active job execution slot."""
        with self._lock:
            self._active_count = max(0, self._active_count - 1)


# Module-level singleton
workload_protector = WorkloadProtector()
