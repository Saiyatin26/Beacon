"""Central config for BEACON. All stages import settings from here instead of
reading os.environ directly, so tuning the scoring defaults means editing .env,
not hunting through every module."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    voyage_api_key: str = os.getenv("VOYAGE_API_KEY", "")

    mongodb_atlas_uri: str = os.getenv("MONGODB_ATLAS_URI", "")
    mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "beacon")

    # Architecture doc Section 7.1
    confidence_threshold: float = 0.7

    # Architecture doc Section 7.2 / 7.3
    severity_weights: dict = {
        "critical": float(os.getenv("SEVERITY_WEIGHT_CRITICAL", "4")),
        "high": float(os.getenv("SEVERITY_WEIGHT_HIGH", "3")),
        "medium": float(os.getenv("SEVERITY_WEIGHT_MEDIUM", "2")),
        "low": float(os.getenv("SEVERITY_WEIGHT_LOW", "1")),
    }

    # Architecture doc Section 7.5
    drift_alert_delta_pct: float = float(os.getenv("DRIFT_ALERT_DELTA_PCT", "2.0"))


settings = Settings()
