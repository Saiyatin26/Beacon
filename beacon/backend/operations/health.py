"""Operational Health Subsystem for BEACON.

Provides distinct operational health dimensions:
1. Liveness: Process is alive and responding (does not fail for temporary external provider outages).
2. Readiness: System is capable of accepting certification work (validates DB, registries, storage).
   IMPORTANT: This is strictly READ-ONLY — it never creates, registers, or modifies any state.
3. Dependency Health: Granular status of DB, registries, and multi-provider hierarchy.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from common.config import settings
from certification.repository import certification_repository
from oracle.registry import registry as oracle_registry
from ingestion.dataset_registry import user_dataset_registry

logger = logging.getLogger(__name__)


class VersionInfoResponse(BaseModel):
    """Safe, non-sensitive application version and runtime metadata."""
    service: str = "BEACON"
    version: str = Field(default_factory=lambda: getattr(settings, "beacon_version", "1.0.0"))
    api_version: str = Field(default_factory=lambda: getattr(settings, "api_version", "v1"))
    environment: str = Field(default_factory=lambda: getattr(settings, "beacon_env", "production"))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LivenessResponse(BaseModel):
    status: Literal["UP", "DOWN"] = "UP"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    service: str = "BEACON"
    version: str = Field(default_factory=lambda: getattr(settings, "beacon_version", "1.0.0"))


class DependencyStatus(BaseModel):
    name: str
    status: Literal["healthy", "degraded", "unavailable", "not_configured"]
    category: str
    details: dict[str, Any] = Field(default_factory=dict)


class ReadinessResponse(BaseModel):
    status: Literal["READY", "NOT_READY"]
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    service: str = "BEACON"
    checks: dict[str, bool] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class HealthDetailsResponse(BaseModel):
    status: Literal["HEALTHY", "DEGRADED", "UNAVAILABLE"]
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    service: str = "BEACON"
    liveness: str = "UP"
    readiness: str
    dependencies: dict[str, DependencyStatus]


def get_version_info() -> VersionInfoResponse:
    """Returns safe, non-sensitive version and build metadata."""
    return VersionInfoResponse()


def check_liveness() -> LivenessResponse:
    """Answers: Is the BEACON process alive and responding?
    Fast, non-blocking check that does not fail if external systems are unreachable.
    """
    return LivenessResponse(status="UP")



def _get_oracleset_health() -> tuple[bool, str, dict[str, Any], Optional[str]]:
    """Authoritative, strictly READ-ONLY check of OracleSet availability.
    
    Inspects oracle_registry directly without creating, registering,
    or mutating any OracleSets or benchmarks.

    Returns:
        (is_ready, status_str, details_dict, error_reason_if_any)
        where status_str is 'healthy' or 'unavailable'.
    """
    try:
        registered_sets = oracle_registry.list_oracle_sets()
        set_count = len(registered_sets)
        if set_count > 0:
            return (
                True,
                "healthy",
                {"oracle_set_count": set_count},
                None,
            )
        else:
            logger.warning("Readiness check: OracleSet registry is empty (expected startup initialization)")
            return (
                False,
                "unavailable",
                {"oracle_set_count": 0},
                "oracle_set_registry_empty",
            )
    except Exception:
        logger.warning("Readiness check: OracleSet registry check failed", exc_info=True)
        return (
            False,
            "unavailable",
            {"oracle_set_count": 0},
            "oracle_set_registry_unavailable",
        )


def check_readiness() -> ReadinessResponse:
    """Answers: Is BEACON currently able to accept certification work safely?

    STRICTLY READ-ONLY: This function inspects current state only.
    It must never create OracleSets, register adapters, modify the database,
    or perform any state-mutating operation.

    OracleSets are initialized at application startup by on_startup().
    This function only reports whether required resources are currently present.
    """
    checks: dict[str, bool] = {}
    reasons: list[str] = []

    # 1. Database Check — READ ONLY (SELECT 1 probe)
    db_ok = False
    try:
        db_path = getattr(certification_repository, "_db_path", "beacon.sqlite3")
        with sqlite3.connect(db_path, timeout=2.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_ok = True
    except Exception:
        logger.warning("Readiness check: database connectivity unavailable", exc_info=True)
        reasons.append("database_unavailable")
    checks["database"] = db_ok

    # 2. Benchmark Registry Check — READ ONLY
    bench_ok = False
    try:
        from benchmarks import benchmark_registry
        benchmarks = benchmark_registry.list_benchmarks()
        bench_ok = len(benchmarks) > 0
        if not bench_ok:
            reasons.append("benchmark_registry_empty")
    except Exception:
        logger.warning("Readiness check: benchmark registry unavailable", exc_info=True)
        reasons.append("benchmark_registry_unavailable")
    checks["benchmark_registry"] = bench_ok

    # 3. OracleSet Registry Check — STRICTLY READ ONLY via authoritative helper
    oracle_ok, _, _, oracle_reason = _get_oracleset_health()
    checks["oracle_set_registry"] = oracle_ok
    if not oracle_ok and oracle_reason:
        reasons.append(oracle_reason)

    # 4. Dataset Registry Check — READ ONLY (attribute presence)
    ds_ok = False
    try:
        ds_ok = hasattr(user_dataset_registry, "list_datasets") or hasattr(user_dataset_registry, "_memory_datasets")
    except Exception:
        logger.warning("Readiness check: dataset registry unavailable", exc_info=True)
        reasons.append("dataset_registry_unavailable")
    checks["dataset_registry"] = ds_ok

    # 5. Certification Repository Check — READ ONLY (attribute presence)
    repo_ok = False
    try:
        repo_ok = hasattr(certification_repository, "get_artifact")
    except Exception:
        logger.warning("Readiness check: certification repository unavailable", exc_info=True)
        reasons.append("certification_repository_unavailable")
    checks["certification_repository"] = repo_ok

    all_ready = all(checks.values())
    return ReadinessResponse(
        status="READY" if all_ready else "NOT_READY",
        checks=checks,
        reasons=reasons,
    )


def check_dependency_health() -> HealthDetailsResponse:
    """Provides granular, non-sensitive health details across all dependencies.
    Never exposes API keys, tokens, auth headers, passwords, filesystem paths,
    hostnames, or raw exception messages.
    """
    readiness = check_readiness()
    deps: dict[str, DependencyStatus] = {}

    # 1. Database
    db_status: Literal["healthy", "unavailable"] = "healthy" if readiness.checks.get("database") else "unavailable"
    deps["database"] = DependencyStatus(
        name="SQLite Storage",
        status=db_status,
        category="storage",
        details={"engine": "sqlite3", "read_write": db_status == "healthy"},
    )

    # 2. Benchmark Registry
    bench_count = 0
    try:
        from benchmarks import benchmark_registry
        bench_count = len(benchmark_registry.list_benchmarks()) if hasattr(benchmark_registry, "list_benchmarks") else 0
    except Exception:
        pass
    bench_status: Literal["healthy", "unavailable"] = "healthy" if bench_count > 0 else "unavailable"
    deps["benchmark_registry"] = DependencyStatus(
        name="Benchmark Registry",
        status=bench_status,
        category="registry",
        details={"benchmark_count": bench_count},
    )

    # 3. OracleSet Registry — STRICTLY READ ONLY via authoritative helper
    oracle_ok, oracle_status, oracle_details, _ = _get_oracleset_health()
    deps["oracle_set_registry"] = DependencyStatus(
        name="OracleSet Registry",
        status=oracle_status,
        category="registry",
        details=oracle_details,
    )

    # 4. Dataset Registry
    ds_ok = readiness.checks.get("dataset_registry", False)
    deps["dataset_registry"] = DependencyStatus(
        name="Dataset Registry",
        status="healthy" if ds_ok else "unavailable",
        category="registry",
        details={"storage_type": "in-memory / file"},
    )

    # 5. Certification Repository
    repo_ok = readiness.checks.get("certification_repository", False)
    deps["certification_repository"] = DependencyStatus(
        name="Certification Repository",
        status="healthy" if repo_ok else "unavailable",
        category="core",
        details={"mode": "atomic_immutable_sqlite"},
    )

    # 6. LLM Multi-Provider Hierarchy (Sanitized — zero secrets, zero paths)
    try:
        from llm.manager import get_provider_manager
        pm = get_provider_manager()
        llm_status = pm.get_status()
        providers_dict = llm_status.get("providers", {})

        for p_name, p_info in providers_dict.items():
            is_avail = p_info.get("available", False)
            is_conf = p_info.get("configured", is_avail)

            if p_name == "offline":
                status_val: Literal["healthy", "degraded", "unavailable", "not_configured"] = "healthy"
            elif is_avail:
                status_val = "healthy"
            elif is_conf:
                status_val = "degraded"
            else:
                status_val = "not_configured"

            deps[f"provider_{p_name}"] = DependencyStatus(
                name=f"LLM Provider: {p_name.capitalize()}",
                status=status_val,
                category="provider",
                details={
                    "role": p_info.get("role", "LLM Provider"),
                    "model": p_info.get("model", "unknown"),
                    "available": is_avail,
                    "configured": is_conf,
                },
            )
    except Exception:
        logger.warning("Dependency health: LLM provider status check failed", exc_info=True)
        deps["provider_offline"] = DependencyStatus(
            name="LLM Provider: Offline",
            status="healthy",
            category="provider",
            details={"available": True, "configured": True},
        )

    # Overall system health: HEALTHY if ready, DEGRADED if optional providers down, UNAVAILABLE if not ready
    overall_status: Literal["HEALTHY", "DEGRADED", "UNAVAILABLE"] = "HEALTHY"
    if readiness.status == "NOT_READY":
        overall_status = "UNAVAILABLE"
    elif any(d.status in ("degraded", "not_configured") for d in deps.values() if d.category == "provider"):
        overall_status = "DEGRADED"

    return HealthDetailsResponse(
        status=overall_status,
        readiness=readiness.status,
        dependencies=deps,
    )




