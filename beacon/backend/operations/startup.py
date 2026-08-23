"""Startup Configuration Validation & Diagnostics for BEACON.

Validates core requirements at application boot without failing for optional providers.
Never outputs secrets, API keys, or private authorization credentials.
"""

import logging
import hashlib
import sqlite3
from typing import Any

from common.config import settings
from certification.repository import certification_repository
from benchmarks import benchmark_registry
from oracle.registry import registry as oracle_registry
from llm.manager import get_provider_manager

logger = logging.getLogger("beacon.startup")


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
    if env == "production" and not getattr(settings, "jwt_secret_key", ""):
        logger.critical("Startup check failed: JWT_SECRET_KEY is mandatory in production environment.")
        raise RuntimeError("Mandatory security configuration failure: JWT_SECRET_KEY missing in production.")
    
    diagnostics["checks"]["security"] = {
        "auth_required": getattr(settings, "auth_required", True),
        "jwt_algorithm": getattr(settings, "jwt_algorithm", "HS256"),
        "environment": env,
    }

    logger.info("BEACON startup configuration validation completed successfully.")
    return diagnostics
