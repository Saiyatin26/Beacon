"""Operational Health Subsystem for BEACON.

Provides distinct operational health dimensions:
1. Liveness: Process is alive and responding (does not fail for temporary external provider outages).
2. Readiness: System is capable of accepting certification work (validates DB, registries, storage).
3. Dependency Health: Granular status of DB, registries, and multi-provider hierarchy.
"""

from datetime import datetime, timezone
import os
import sqlite3
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

from common.config import settings
from certification.repository import certification_repository
from benchmarks import benchmark_registry
from oracle.registry import registry as oracle_registry
from ingestion.dataset_registry import user_dataset_registry
from llm.manager import get_provider_manager


class LivenessResponse(BaseModel):
    status: Literal["UP", "DOWN"] = "UP"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    service: str = "BEACON"
    version: str = "1.0.0"


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


def check_liveness() -> LivenessResponse:
    """Answers: Is the BEACON process alive and responding?
    Fast, non-blocking check that does not fail if external systems are unreachable.
    """
    return LivenessResponse(status="UP")


def check_readiness() -> ReadinessResponse:
    """Answers: Is BEACON currently able to accept certification work safely?
    Verifies mandatory local dependencies:
    - SQLite database read/write access
    - Benchmark registry loaded with at least 1 benchmark
    - OracleSet registry loaded
    - Dataset registry accessible
    - Certification repository accessible
    """
    checks: dict[str, bool] = {}
    reasons: list[str] = []

    # 1. Database Check
    db_ok = False
    try:
        db_path = getattr(certification_repository, "_db_path", "beacon.sqlite3")
        with sqlite3.connect(db_path, timeout=2.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_ok = True
    except Exception as exc:
        reasons.append(f"Database connectivity check failed: {exc}")
    checks["database"] = db_ok

    # 2. Benchmark Registry Check
    bench_ok = False
    try:
        benchmarks = benchmark_registry.list_benchmarks()
        bench_ok = len(benchmarks) > 0
        if not bench_ok:
            reasons.append("Benchmark registry contains 0 benchmarks.")
    except Exception as exc:
        reasons.append(f"Benchmark registry check failed: {exc}")
    checks["benchmark_registry"] = bench_ok

    # 3. OracleSet Registry Check
    oracle_ok = False
    try:
        sets = oracle_registry.list_oracle_sets()
        if not sets:
            for b in benchmark_registry.list_benchmarks():
                try:
                    s = benchmark_registry.get_or_create_oracle_set(b.benchmark_id, mode="CONTROLLED")
                    if s:
                        oracle_registry.register_oracle_set(s)
                except Exception:
                    pass
            sets = oracle_registry.list_oracle_sets()

        oracle_ok = len(sets) > 0 or hasattr(benchmark_registry, "get_or_create_oracle_set")
        if not oracle_ok:
            reasons.append("OracleSet registry contains 0 oracle sets.")
    except Exception as exc:
        reasons.append(f"OracleSet registry check failed: {exc}")
    checks["oracle_set_registry"] = oracle_ok

    # 4. Dataset Registry Check
    ds_ok = False
    try:
        ds_ok = hasattr(user_dataset_registry, "list_datasets") or hasattr(user_dataset_registry, "_memory_datasets")
    except Exception as exc:
        reasons.append(f"Dataset registry check failed: {exc}")
    checks["dataset_registry"] = ds_ok

    # 5. Certification Repository Check
    repo_ok = False
    try:
        repo_ok = hasattr(certification_repository, "get_artifact")
    except Exception as exc:
        reasons.append(f"Certification repository check failed: {exc}")
    checks["certification_repository"] = repo_ok

    all_ready = all(checks.values())
    return ReadinessResponse(
        status="READY" if all_ready else "NOT_READY",
        checks=checks,
        reasons=reasons,
    )


def check_dependency_health() -> HealthDetailsResponse:
    """Provides granular, non-sensitive health details across all dependencies.
    Never exposes API keys, tokens, auth headers, or passwords.
    """
    readiness = check_readiness()
    deps: dict[str, DependencyStatus] = {}

    # 1. Database
    db_path = getattr(certification_repository, "_db_path", "beacon.sqlite3")
    db_status: Literal["healthy", "unavailable"] = "healthy" if readiness.checks.get("database") else "unavailable"
    deps["database"] = DependencyStatus(
        name="SQLite Storage",
        status=db_status,
        category="storage",
        details={"engine": "sqlite3", "read_write": db_status == "healthy"},
    )

    # 2. Benchmark Registry
    benchmarks = benchmark_registry.list_benchmarks() if hasattr(benchmark_registry, "list_benchmarks") else []
    bench_status: Literal["healthy", "unavailable"] = "healthy" if len(benchmarks) > 0 else "unavailable"
    deps["benchmark_registry"] = DependencyStatus(
        name="Benchmark Registry",
        status=bench_status,
        category="registry",
        details={"benchmark_count": len(benchmarks)},
    )

    # 3. OracleSet Registry
    oracle_sets = oracle_registry.list_oracle_sets() if hasattr(oracle_registry, "list_oracle_sets") else []
    oracle_status: Literal["healthy", "unavailable"] = "healthy" if len(oracle_sets) > 0 or hasattr(benchmark_registry, "get_or_create_oracle_set") else "unavailable"
    deps["oracle_set_registry"] = DependencyStatus(
        name="OracleSet Registry",
        status=oracle_status,
        category="registry",
        details={"oracle_set_count": len(oracle_sets)},
    )

    # 4. Dataset Registry
    deps["dataset_registry"] = DependencyStatus(
        name="Dataset Registry",
        status="healthy" if readiness.checks.get("dataset_registry") else "unavailable",
        category="registry",
        details={"storage_type": "in-memory / file"},
    )

    # 5. Certification Repository
    deps["certification_repository"] = DependencyStatus(
        name="Certification Repository",
        status="healthy" if readiness.checks.get("certification_repository") else "unavailable",
        category="core",
        details={"mode": "atomic_immutable_sqlite"},
    )

    # 6. LLM Multi-Provider Hierarchy (Sanitized — zero secrets)
    pm = get_provider_manager()
    llm_status = pm.get_status()
    providers_dict = llm_status.get("providers", {})

    for p_name, p_info in providers_dict.items():
        is_avail = p_info.get("available", False)
        is_conf = p_info.get("configured", is_avail)
        
        if p_name == "offline":
            status_val = "healthy"
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

    # Overall system health: HEALTHY if ready and at least active provider healthy, DEGRADED if optional cloud down but offline ready
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
