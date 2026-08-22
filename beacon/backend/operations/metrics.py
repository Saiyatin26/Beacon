"""Operational Metrics Collector for BEACON.

Provides aggregated runtime statistics, throughput counters, latency averages,
and error frequency metrics. Does NOT store raw customer inputs, secrets, or high-cardinality data.
"""

from datetime import datetime, timezone
import threading
from typing import Any, Optional
from pydantic import BaseModel, Field


class MetricsSnapshot(BaseModel):
    """Aggregated operational metrics representation."""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    service: str = "BEACON"
    
    # Run Counters
    certification_runs_total: int = 0
    certification_runs_successful: int = 0
    certification_runs_failed: int = 0
    active_certification_jobs: int = 0
    
    # Status Breakdown
    certification_status_breakdown: dict[str, int] = Field(default_factory=dict)
    
    # Failures & Fallbacks
    preflight_failures: int = 0
    dataset_ingestion_failures: int = 0
    provider_failures: int = 0
    provider_fallbacks: int = 0
    integrity_verification_failures: int = 0
    export_failures: int = 0
    
    # Performance Averages
    avg_certification_duration_ms: float = 0.0
    avg_preflight_duration_ms: float = 0.0
    avg_provider_latency_ms: float = 0.0


class OperationalMetricsCollector:
    """Thread-safe in-memory operational metrics collector."""

    def __init__(self):
        self._lock = threading.RLock()
        self._runs_total: int = 0
        self._runs_successful: int = 0
        self._runs_failed: int = 0
        self._status_counts: dict[str, int] = {}
        
        self._preflight_failures: int = 0
        self._ingestion_failures: int = 0
        self._provider_failures: int = 0
        self._provider_fallbacks: int = 0
        self._integrity_failures: int = 0
        self._export_failures: int = 0
        
        self._cert_durations: list[float] = []
        self._preflight_durations: list[float] = []
        self._provider_latencies: list[float] = []
        self._active_jobs: int = 0
        # Project-level counters for scoped metrics
        self._project_runs: dict[str, int] = {}
        self._project_successful: dict[str, int] = {}
        self._project_failed: dict[str, int] = {}
        self._project_status_counts: dict[str, dict[str, int]] = {}
        self._project_durations: dict[str, list[float]] = {}

    def record_job_started(self) -> None:
        with self._lock:
            self._active_jobs = max(0, self._active_jobs + 1)

    def record_job_completed(
        self,
        duration_ms: float,
        certification_status: Optional[str] = None,
        success: bool = True,
        project_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._active_jobs = max(0, self._active_jobs - 1)
            self._runs_total += 1
            if success:
                self._runs_successful += 1
            else:
                self._runs_failed += 1

            if certification_status:
                self._status_counts[certification_status] = self._status_counts.get(certification_status, 0) + 1

            if duration_ms > 0:
                self._cert_durations.append(duration_ms)
                if len(self._cert_durations) > 500:
                    self._cert_durations.pop(0)

            # Project-scoped tracking
            if project_id:
                self._project_runs[project_id] = self._project_runs.get(project_id, 0) + 1
                if success:
                    self._project_successful[project_id] = self._project_successful.get(project_id, 0) + 1
                else:
                    self._project_failed[project_id] = self._project_failed.get(project_id, 0) + 1
                if certification_status:
                    ps = self._project_status_counts.setdefault(project_id, {})
                    ps[certification_status] = ps.get(certification_status, 0) + 1
                if duration_ms > 0:
                    pd = self._project_durations.setdefault(project_id, [])
                    pd.append(duration_ms)
                    if len(pd) > 200:
                        pd.pop(0)

    def record_job_failed(self, error_category: Optional[str] = None, project_id: Optional[str] = None) -> None:
        with self._lock:
            self._active_jobs = max(0, self._active_jobs - 1)
            self._runs_total += 1
            self._runs_failed += 1
            if project_id:
                self._project_runs[project_id] = self._project_runs.get(project_id, 0) + 1
                self._project_failed[project_id] = self._project_failed.get(project_id, 0) + 1

    def record_preflight_event(self, duration_ms: float, success: bool = True) -> None:
        with self._lock:
            if duration_ms > 0:
                self._preflight_durations.append(duration_ms)
                if len(self._preflight_durations) > 200:
                    self._preflight_durations.pop(0)
            if not success:
                self._preflight_failures += 1

    def record_ingestion_failure(self) -> None:
        with self._lock:
            self._ingestion_failures += 1

    def record_provider_event(self, latency_ms: float, fallback: bool = False, success: bool = True) -> None:
        with self._lock:
            if latency_ms > 0:
                self._provider_latencies.append(latency_ms)
                if len(self._provider_latencies) > 200:
                    self._provider_latencies.pop(0)
            if fallback:
                self._provider_fallbacks += 1
            if not success:
                self._provider_failures += 1

    def record_integrity_failure(self) -> None:
        with self._lock:
            self._integrity_failures += 1

    def record_export_failure(self) -> None:
        with self._lock:
            self._export_failures += 1

    def get_snapshot(self) -> MetricsSnapshot:
        """Returns a global aggregate snapshot (for backward compatibility)."""
        with self._lock:
            avg_cert = sum(self._cert_durations) / len(self._cert_durations) if self._cert_durations else 0.0
            avg_pref = sum(self._preflight_durations) / len(self._preflight_durations) if self._preflight_durations else 0.0
            avg_prov = sum(self._provider_latencies) / len(self._provider_latencies) if self._provider_latencies else 0.0

            return MetricsSnapshot(
                certification_runs_total=self._runs_total,
                certification_runs_successful=self._runs_successful,
                certification_runs_failed=self._runs_failed,
                active_certification_jobs=self._active_jobs,
                certification_status_breakdown=dict(self._status_counts),
                preflight_failures=self._preflight_failures,
                dataset_ingestion_failures=self._ingestion_failures,
                provider_failures=self._provider_failures,
                provider_fallbacks=self._provider_fallbacks,
                integrity_verification_failures=self._integrity_failures,
                export_failures=self._export_failures,
                avg_certification_duration_ms=round(avg_cert, 2),
                avg_preflight_duration_ms=round(avg_pref, 2),
                avg_provider_latency_ms=round(avg_prov, 2),
            )

    def get_project_snapshot(self, project_id: str) -> dict:
        """Returns a project-scoped metrics snapshot. Only includes data for the given project."""
        with self._lock:
            runs = self._project_runs.get(project_id, 0)
            successful = self._project_successful.get(project_id, 0)
            failed = self._project_failed.get(project_id, 0)
            status_breakdown = dict(self._project_status_counts.get(project_id, {}))
            durations = self._project_durations.get(project_id, [])
            avg_cert = sum(durations) / len(durations) if durations else 0.0
            return {
                "project_id": project_id,
                "certification_runs_total": runs,
                "certification_runs_successful": successful,
                "certification_runs_failed": failed,
                "certification_status_breakdown": status_breakdown,
                "avg_certification_duration_ms": round(avg_cert, 2),
                "active_certification_jobs": self._active_jobs,
            }

    def clear(self) -> None:
        """Clears all metric counters (used for clean testing)."""
        with self._lock:
            self._runs_total = 0
            self._runs_successful = 0
            self._runs_failed = 0
            self._status_counts.clear()
            self._preflight_failures = 0
            self._ingestion_failures = 0
            self._provider_failures = 0
            self._provider_fallbacks = 0
            self._integrity_failures = 0
            self._export_failures = 0
            self._cert_durations.clear()
            self._preflight_durations.clear()
            self._provider_latencies.clear()
            self._active_jobs = 0
            self._project_runs.clear()
            self._project_successful.clear()
            self._project_failed.clear()
            self._project_status_counts.clear()
            self._project_durations.clear()


# Module-level singleton
operational_metrics = OperationalMetricsCollector()
