"""BEACON V2 — Phase 3 Extensible Evidence Providers.

Implements pluggable collectors for output observations, system logs, lifecycle traces,
filesystem snapshots, HTTP telemetry, and runtime context.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any, Optional
from pydantic import BaseModel

from common.contracts import Observation
from .evidence_models import (
    DatabaseEvidence,
    EvidenceCaptureStatus,
    EvidenceConfiguration,
    EvidenceRecord,
    EvidenceType,
    FileEvidence,
    FileStateSnapshot,
    HttpEvidence,
    LogEvidence,
    MetadataEvidence,
    OutputEvidence,
    RuntimeEvidence,
    TraceEvent,
    TraceEvidence,
    compute_content_hash,
)
from .security import SecretRedactor

logger = logging.getLogger("beacon.execution.evidence_providers")


class EvidenceProvider(ABC):
    """Abstract interface for modular behavioral evidence collectors."""

    provider_name: str = "base"
    evidence_type: EvidenceType = EvidenceType.OUTPUT

    def prepare(self, context: Optional[dict[str, Any]] = None) -> None:
        """Invoked before the application is started."""
        pass

    def capture_before(self, context: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        """Invoked immediately prior to executing an input."""
        return None

    def capture_after(
        self,
        observation: Optional[Observation] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Invoked immediately following input execution."""
        return None

    def cleanup(self) -> None:
        """Invoked during post-execution cleanup."""
        pass


class OutputEvidenceProvider(EvidenceProvider):
    """Extracts output facts (normalized and raw outputs, exit code, stderr, duration)."""

    provider_name: str = "output_provider"
    evidence_type: EvidenceType = EvidenceType.OUTPUT

    def capture_after(
        self,
        observation: Optional[Observation] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if not observation:
            return OutputEvidence(
                execution_status="FAILED",
                error_message="No observation available.",
            ).model_dump()

        prov = observation.provenance or {}
        output = OutputEvidence(
            raw_output=observation.raw_outputs,
            normalized_output=observation.normalized_outputs,
            stdout=prov.get("stdout"),
            stderr=prov.get("stderr"),
            exit_code=prov.get("exit_code"),
            http_status=prov.get("http_status") or prov.get("status_code"),
            headers=prov.get("headers"),
            duration_ms=observation.execution_time_ms,
            execution_status=observation.execution_status,
            error_message=observation.error_message,
        )
        return output.model_dump()


class LogEvidenceProvider(EvidenceProvider):
    """Captures process and adapter log streams with capability detection."""

    provider_name: str = "log_provider"
    evidence_type: EvidenceType = EvidenceType.LOG

    def capture_after(
        self,
        observation: Optional[Observation] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if not observation:
            return LogEvidence(
                log_status=EvidenceCaptureStatus.NOT_AVAILABLE,
            ).model_dump()

        prov = observation.provenance or {}
        stdout_txt = prov.get("stdout")
        stderr_txt = prov.get("stderr")

        has_logs = bool(stdout_txt or stderr_txt)
        status = EvidenceCaptureStatus.CAPTURED if has_logs else EvidenceCaptureStatus.NOT_AVAILABLE

        log_ev = LogEvidence(
            stdout_log=stdout_txt,
            stderr_log=stderr_txt,
            adapter_log=prov.get("adapter_log"),
            startup_log=prov.get("startup_log"),
            shutdown_log=prov.get("shutdown_log"),
            log_status=status,
        )
        return log_ev.model_dump()


class HttpEvidenceProvider(EvidenceProvider):
    """Captures HTTP transaction evidence for REST/HTTP adapters."""

    provider_name: str = "http_provider"
    evidence_type: EvidenceType = EvidenceType.HTTP

    def capture_after(
        self,
        observation: Optional[Observation] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        ctx = context or {}
        prov = (observation.provenance if observation else {}) or {}

        # If this wasn't an HTTP adapter run, record not supported
        if prov.get("adapter_type") != "http" and ctx.get("adapter_type") != "http":
            return {
                "status": EvidenceCaptureStatus.NOT_SUPPORTED.value,
                "message": "HTTP evidence not supported for non-HTTP adapter.",
            }

        headers = prov.get("headers") or {}
        safe_headers = SecretRedactor.redact(headers)

        http_ev = HttpEvidence(
            method=prov.get("method") or "POST",
            url_or_endpoint=prov.get("endpoint") or prov.get("url") or "",
            request_headers=safe_headers if isinstance(safe_headers, dict) else {},
            request_body=observation.raw_inputs if observation else None,
            response_status=prov.get("status_code") or prov.get("http_status"),
            response_headers=prov.get("response_headers", {}),
            response_body=observation.raw_outputs if observation else None,
            latency_ms=observation.execution_time_ms if observation else 0.0,
            correlation_id=ctx.get("correlation_id"),
        )
        return http_ev.model_dump()


class FileEvidenceProvider(EvidenceProvider):
    """Tracks filesystem state changes on explicitly configured paths before and after execution."""

    provider_name: str = "filesystem_provider"
    evidence_type: EvidenceType = EvidenceType.FILESYSTEM

    def __init__(self, paths: Optional[list[str]] = None):
        self.paths = paths or []
        self._before_snapshots: dict[str, FileStateSnapshot] = {}

    def _snapshot_path(self, path_str: str) -> FileStateSnapshot:
        p = Path(path_str)
        if not p.exists():
            return FileStateSnapshot(path=path_str, exists=False)

        try:
            st = p.stat()
            is_file = p.is_file()
            size = st.st_size
            mod_time = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
            sha256 = None
            if is_file and size < 10 * 1024 * 1024:  # Cap hash calculation at 10MB
                with open(p, "rb") as f:
                    sha256 = hashlib.sha256(f.read()).hexdigest()

            return FileStateSnapshot(
                path=path_str,
                exists=True,
                is_file=is_file,
                size_bytes=size,
                sha256_hash=sha256,
                modified_at=mod_time,
            )
        except Exception as exc:
            logger.warning(f"Failed to snapshot path '{path_str}': {exc}")
            return FileStateSnapshot(path=path_str, exists=True, sha256_hash=f"ERROR:{exc}")

    def capture_before(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self._before_snapshots = {path: self._snapshot_path(path) for path in self.paths}
        return {k: v.model_dump() for k, v in self._before_snapshots.items()}

    def capture_after(
        self,
        observation: Optional[Observation] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        after_snapshots = {path: self._snapshot_path(path) for path in self.paths}
        delta_detected = False

        for path, before_snap in self._before_snapshots.items():
            after_snap = after_snapshots.get(path)
            if not after_snap:
                delta_detected = True
                break
            if before_snap.exists != after_snap.exists or before_snap.sha256_hash != after_snap.sha256_hash:
                delta_detected = True
                break

        fe = FileEvidence(
            configured_paths=self.paths,
            before_state=self._before_snapshots,
            after_state=after_snapshots,
            delta_detected=delta_detected,
            status=EvidenceCaptureStatus.CAPTURED if self.paths else EvidenceCaptureStatus.NOT_AVAILABLE,
        )
        return fe.model_dump()


class DatabaseEvidenceProvider(EvidenceProvider):
    """Extensible database snapshot provider."""

    provider_name: str = "database_provider"
    evidence_type: EvidenceType = EvidenceType.DATABASE

    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = config or {}

    def capture_after(
        self,
        observation: Optional[Observation] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if not self.config:
            return DatabaseEvidence(
                provider_name="none",
                status=EvidenceCaptureStatus.NOT_SUPPORTED,
                message="No database state capture configured.",
            ).model_dump()

        return DatabaseEvidence(
            provider_name=self.config.get("provider", "custom"),
            status=EvidenceCaptureStatus.CAPTURED,
            snapshot_before=self.config.get("snapshot_before"),
            snapshot_after=self.config.get("snapshot_after"),
            message="Database snapshot recorded.",
        ).model_dump()


class TraceEvidenceProvider(EvidenceProvider):
    """Maintains an ordered timeline of lifecycle events."""

    provider_name: str = "trace_provider"
    evidence_type: EvidenceType = EvidenceType.TRACE

    def __init__(self):
        self.events: list[TraceEvent] = []
        self._seq = 0

    def record_event(self, event_type: str, source: str = "runner", details: Optional[dict[str, Any]] = None) -> TraceEvent:
        self._seq += 1
        ev_id = f"TRC-{hashlib.sha256(f'{self._seq}_{event_type}_{time.perf_counter()}'.encode()).hexdigest()[:10]}"
        evt = TraceEvent(
            event_id=ev_id,
            sequence=self._seq,
            event_type=event_type,
            source=source,
            details=details or {},
        )
        self.events.append(evt)
        return evt

    def capture_after(
        self,
        observation: Optional[Observation] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return TraceEvidence(events=list(self.events)).model_dump()

    def cleanup(self) -> None:
        self.events.clear()
        self._seq = 0


class RuntimeEvidenceProvider(EvidenceProvider):
    """Captures operating system, Python, and adapter runtime metadata."""

    provider_name: str = "runtime_provider"
    evidence_type: EvidenceType = EvidenceType.RUNTIME

    def capture_after(
        self,
        observation: Optional[Observation] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        ctx = context or {}
        adapter = ctx.get("adapter")
        role = str(getattr(adapter, "role", ctx.get("role", "target")))
        adp_name = getattr(adapter, "name", ctx.get("adapter_name", "unnamed"))
        adp_ver = getattr(adapter, "version", ctx.get("adapter_version", "1.0.0"))
        adp_type = getattr(adapter, "adapter_type", type(adapter).__name__ if adapter else "unknown")

        re = RuntimeEvidence(
            os=f"{platform.system()} {platform.release()}",
            architecture=platform.machine(),
            python_version=platform.python_version(),
            hostname=platform.node() or "localhost",
            runtime_version=sys.version.split(" ")[0],
            environment_id=os.getenv("BEACON_ENV", "test"),
            adapter_name=adp_name,
            adapter_version=adp_ver,
            adapter_type=adp_type,
            role=role,
        )
        return re.model_dump()
