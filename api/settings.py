from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings; secret values are read from referenced files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    grp_env: str = "dev"
    grp_public_base_url: str = "http://127.0.0.1:8000"
    storage_root: Path = Path(".local/data")
    database_url_file: Path = Path(".local/secrets/database_url")

    human_identity_provider: str = "servir_sig"
    auth_callback_path: str = "/api/v1/auth/callback"
    session_idle_minutes: int = 60
    session_max_hours: int = 12

    worker_concurrency: int = 1
    job_lease_minutes: int = 15

    ai_feature_enabled: bool = False
    ai_timezone: str = "Asia/Bangkok"
    rate_limits: dict[str, int] = Field(
        default_factory=lambda: {
            "api_requests_per_person_per_minute": 60,
            "new_assessments_per_person_per_hour": 10,
            "sig_evidence_reads_per_minute": 30,
            "ai_requests_per_person_per_hour": 20,
        }
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
