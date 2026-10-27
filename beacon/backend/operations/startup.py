"""Startup Configuration Validation & Diagnostics for BEACON.

Validates core requirements at application boot without failing for optional providers.
Never outputs secrets, API keys, or private authorization credentials.
"""

import logging
import hashlib
import os
import sqlite3
from typing import Any

from common.config import settings
from certification.repository import certification_repository
from oracle.registry import registry as oracle_registry
from llm.manager import get_provider_manager
from .job_lifecycle import certification_job_tracker, JobState
from .logging_config import log_operational_event

logger = logging.getLogger("beacon.startup")


def recover_interrupted_operations() -> dict[str, Any]:
    """Scans persisted jobs that were interrupted in non-terminal states prior to restart,
    and safely marks them as FAILED with operational diagnostic details.
    """
    logger.info("Scanning for interrupted or stale operations from previous run...")
    interrupted_jobs = certification_job_tracker.list_interrupted_or_stale_jobs()
    recovered_count = 0

    for job in interrupted_jobs:
        try:
            logger.warning(
                f"Recovering interrupted job '{job.job_id}' (previous state: '{job.state.value}') "
                f"for project '{job.project_id}'."
            )
            certification_job_tracker.update_state(
                job_id=job.job_id,
                state=JobState.FAILED,
                current_step="Operation interrupted by application restart/shutdown.",
                error_category="INTERRUPTED",
                error_message="Job was interrupted in-flight by a server restart or process termination.",
                allow_forced=True,
            )
            log_operational_event(
                event="job_recovery_interrupted_handled",
                project_id=job.project_id,
                level=logging.WARNING,
                logger_name="beacon.startup",
                outcome="RECOVERED_TO_FAILED",
                error_category="INTERRUPTED",
                message=f"Interrupted job '{job.job_id}' safely recovered and marked FAILED",
                extra={"job_id": job.job_id, "previous_state": job.state.value},
            )
            recovered_count += 1
        except Exception as exc:
            logger.error(f"Failed to recover interrupted job '{job.job_id}': {exc}")

    logger.info(f"Startup recovery completed: {recovered_count} interrupted jobs processed.")
    return {"interrupted_jobs_found": len(interrupted_jobs), "recovered_count": recovered_count}


def validate_startup_configuration() -> dict[str, Any]:
    """Validates configuration at startup and returns a sanitized diagnostic summary.
    Raises RuntimeError ONLY if a mandatory dependency (e.g. Database, Registries) is completely unusable.
    """
    logger.info("Initializing BEACON production environment startup validation...")
    diagnostics: dict[str, Any] = {"status": "SUCCESS", "checks": {}, "warnings": []}

    # 1. Cryptographic System Check
    try:
        test_digest = hashlib.sha256(b"beacon_startup_test").hexdigest()
        assert len(test_digest) == 64
        diagnostics["checks"]["cryptography"] = "OK"
    except Exception as exc:
        logger.critical(f"Startup check failed: Cryptographic hashing unavailable: {exc}")
        raise RuntimeError(f"Cryptographic subsystem failure: {exc}")

    # 2. Database Connectivity & Table Check
    try:
        db_path = getattr(certification_repository, "_db_path", "beacon.sqlite3")
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]
        diagnostics["checks"]["database"] = {"status": "OK", "tables_detected": len(tables)}
        logger.info(f"Database connection verified at '{db_path}' ({len(tables)} tables present).")
    except Exception as exc:
        logger.critical(f"Startup check failed: Database connection failed: {exc}")
        raise RuntimeError(f"Mandatory database check failed: {exc}")

    # 3. Benchmark Registry Check
    try:
        benchmarks = benchmark_registry.list_benchmarks()
        if not benchmarks:
            diagnostics["warnings"].append("Benchmark registry loaded 0 benchmarks.")
            logger.warning("Benchmark registry is currently empty.")
        else:
            diagnostics["checks"]["benchmarks"] = {"status": "OK", "count": len(benchmarks)}
            logger.info(f"Benchmark registry loaded ({len(benchmarks)} benchmarks ready).")
    except Exception as exc:
        logger.critical(f"Startup check failed: Benchmark registry loading failed: {exc}")
        raise RuntimeError(f"Mandatory benchmark registry failure: {exc}")

    # 4. OracleSet Registry Check
    try:
        oracle_sets = oracle_registry.list_oracle_sets()
        if not oracle_sets:
            diagnostics["warnings"].append("OracleSet registry loaded 0 sets.")
            logger.warning("OracleSet registry is currently empty.")
        else:
            diagnostics["checks"]["oracle_sets"] = {"status": "OK", "count": len(oracle_sets)}
            logger.info(f"OracleSet registry loaded ({len(oracle_sets)} sets ready).")
    except Exception as exc:
        logger.critical(f"Startup check failed: OracleSet registry loading failed: {exc}")
        raise RuntimeError(f"Mandatory OracleSet registry failure: {exc}")

    # 5. LLM Multi-Provider Hierarchy Check (Non-failing for optional providers)
    try:
        pm = get_provider_manager()
        status = pm.get_status()
        active = status.get("active_provider", "offline")
        diagnostics["checks"]["llm_providers"] = {
            "configured_mode": settings.llm_provider,
            "active_provider": active,
            "allow_fallback": settings.allow_auto_fallback,
            "openrouter_configured": bool(settings.openrouter_api_key),
            "anthropic_configured": bool(settings.anthropic_api_key),
            "ollama_available": status.get("providers", {}).get("ollama", {}).get("available", False),
            "offline_deterministic_ready": True,
        }
        logger.info(f"LLM Provider hierarchy initialized. Active provider: '{active}'.")
    except Exception as exc:
        diagnostics["warnings"].append(f"LLM Provider manager check notice: {exc}")
        logger.warning(f"LLM Provider check notice: {exc}")

    # 6. Workload & Resource Limits Check
    diagnostics["checks"]["workload_limits"] = {
        "max_dataset_size_bytes": getattr(settings, "max_dataset_size_bytes", 10 * 1024 * 1024),
        "max_input_records": getattr(settings, "max_input_records", 5000),
        "max_request_body_bytes": getattr(settings, "max_request_body_bytes", 15 * 1024 * 1024),
        "max_concurrent_jobs": getattr(settings, "max_concurrent_jobs", 10),
    }

    # 7. CORS Configuration
    diagnostics["checks"]["cors"] = {
        "allowed_origins_count": len(settings.cors_origins),
    }

    # 8. Authentication & Security Configuration Check
    env = getattr(settings, "beacon_env", "production").lower()
    jwt_secret = getattr(settings, "jwt_secret_key", "") or os.environ.get("JWT_SECRET_KEY", "") or os.environ.get("BEACON_JWT_SECRET", "")
    
    if env == "production":
        if not jwt_secret or len(jwt_secret.strip()) == 0 or len(jwt_secret) < 16:
            logger.critical("Startup check failed: JWT_SECRET_KEY is missing or invalid in production environment.")
            raise RuntimeError("JWT_SECRET_KEY is missing or invalid.")
    elif getattr(settings, "auth_required", True):
        if not jwt_secret or len(jwt_secret.strip()) == 0:
            logger.critical("Startup check failed: JWT_SECRET_KEY is missing or invalid.")
            raise RuntimeError("JWT_SECRET_KEY is missing or invalid.")

    diagnostics["checks"]["security"] = {
        "auth_required": getattr(settings, "auth_required", True),
        "jwt_algorithm": getattr(settings, "jwt_algorithm", "HS256"),
        "environment": env,
    }

    logger.info("BEACON startup configuration validation completed successfully.")
    return diagnostics

