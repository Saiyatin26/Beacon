"""Central config for BEACON. All stages import settings from here instead of
reading os.environ directly, so tuning the scoring defaults means editing .env,
not hunting through every module."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Multi-Provider LLM Configuration (Phases 6 & 7 Provider Decoupling)
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto").lower()
    allow_auto_fallback: bool = os.getenv("ALLOW_AUTO_FALLBACK", "true").lower() in ("true", "1", "yes")

    # Primary Cloud Provider: OpenRouter
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    # Supported Cloud Provider: Anthropic
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    # Local Fallback Provider: Ollama (Qwen / Mistral)
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")

    # Storage & Embeddings
    voyage_api_key: str = os.getenv("VOYAGE_API_KEY", "")
    mongodb_atlas_uri: str = os.getenv("MONGODB_ATLAS_URI", "")
    mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "beacon")

    # Architecture doc Section 7.1
    confidence_threshold: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.8"))

    # Architecture doc Section 7.2 / 7.3
    severity_weights: dict = {
        "critical": float(os.getenv("SEVERITY_WEIGHT_CRITICAL", "4")),
        "high": float(os.getenv("SEVERITY_WEIGHT_HIGH", "3")),
        "medium": float(os.getenv("SEVERITY_WEIGHT_MEDIUM", "2")),
        "low": float(os.getenv("SEVERITY_WEIGHT_LOW", "1")),
    }

    # Architecture doc Section 7.5
    drift_alert_delta_pct: float = float(os.getenv("DRIFT_ALERT_DELTA_PCT", "2.0"))

    # CORS Allowed Origins
    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ]


settings = Settings()

