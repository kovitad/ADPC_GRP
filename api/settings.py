from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
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
    servir_auth_issuer: str | None = None
    servir_auth_client_id: str | None = None
    servir_auth_client_secret_file: Path = Path(".local/secrets/servir_auth_client_secret")
    servir_auth_redirect_uri: str | None = None
    sig_mcp_base_url: str = "https://servirplatform.sig-gis.com/mcp"
    session_secret_file: Path = Path(".local/secrets/session_secret")
    session_idle_minutes: int = 60
    session_max_hours: int = 12

    worker_concurrency: int = 1
    # Draft (not scientifically approved) methods may run only where this is true: local tests.
    allow_draft_methods: bool = False
    job_lease_minutes: int = 15

    ai_feature_enabled: bool = False
    # Planner chat box and map using SIG generic evidence (ADR-0004). Docker Desktop only.
    planning_chat_enabled: bool = False
    # Share Data calls the signed-in person's governed Global Risk MCP tools. Independently
    # switchable on an approved server; false keeps the routes hidden by default.
    global_risk_contributions_enabled: bool = False
    # Admin data inspector over a read-only source folder (ADR-0006). Docker Desktop only.
    data_inspector_enabled: bool = False
    data_in_root: Path = Path(".local/data-in")
    # Local Developer-only pilot: a Platform Admin may upload one shelter Shapefile ZIP into
    # job-scoped quarantine. Servers leave this off until the upload security gate is approved.
    shelter_browser_upload_enabled: bool = False
    shelter_upload_max_bytes: int = 64 * 1024 * 1024
    shelter_upload_max_uncompressed_bytes: int = 128 * 1024 * 1024
    # ADR-0038: the worker pulls the flood pilots' public sources (Floodboard). Off by default so
    # tests and servers stay offline until the pilot is switched on deliberately.
    flood_pilot_pulls_enabled: bool = False
    # ADR-0049: Longdo Weather rain context for live flood pilots. The key lives in a secret file.
    longdo_weather_enabled: bool = False
    longdo_api_key_file: Path = Path(".local/secrets/longdo_api_key")
    # ADR-0065: worker-only ThaiWater government-observation shadow capture. No warnings.
    thaiwater_shadow_enabled: bool = False
    thaiwater_api_key_file: Path = Path(".local/secrets/thaiwater_api_key")
    thaiwater_api_base_url: str = "https://twa-api-public.thaiwater.net"
    thaiwater_poll_minutes: int = Field(default=15, ge=5, le=1440)
    # ADR-0068: anonymous, latest-observation feed for an explicitly approved pilot only.
    thaiwater_feed_public: bool = False
    # ADR-0051: relay bmatraffic.com camera pictures into the flood page. Local demo only; off on
    # servers until BMA gives permission.
    bmatraffic_relay_enabled: bool = False
    # ADR-0052: the anonymous live flood feed for Global Risk. Off unless a public host serves it.
    flood_feed_public: bool = False
    # ADR-0061: the anonymous PM2.5 feed for Global Risk. Off unless a public host serves it.
    air_quality_feed_public: bool = False
    # The permanent public address GRP's feeds are shared from (Share data). Unset: none yet.
    grp_public_feed_base_url: str | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_base_url: str | None = None
    ai_key_file_adpc: Path = Path(".local/secrets/ai_key_adpc")
    ai_max_output_tokens: int = 800
    ai_timezone: str = "Asia/Bangkok"
    ai_timeout_seconds: float = 60.0

    # Langfuse (hosted) receives safe AI call metadata only; it never enforces the allowance.
    langfuse_host: str | None = Field(
        default=None, validation_alias=AliasChoices("LANGFUSE_HOST", "LANGFUSE_BASE_URL")
    )
    langfuse_public_key: str | None = None
    langfuse_secret_key_file: Path = Path(".local/secrets/langfuse_secret_key")
    langfuse_environment: str | None = None

    # SIG machine login, staging fallback (Section 9.6): hash of a long random token.
    sig_service_token_hash_file: Path = Path(".local/secrets/sig_service_token_hash")
    sig_allowed_ips: list[str] = Field(default_factory=list)
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


def planning_chat_available(settings: Settings) -> bool:
    """ADR-0004: the interim planning chat runs only in local development."""

    return settings.planning_chat_enabled and settings.grp_env == "dev"


def global_risk_contributions_available(settings: Settings) -> bool:
    """Share Data is local by default or explicitly enabled on an approved deployment."""

    return planning_chat_available(settings) or settings.global_risk_contributions_enabled


def sig_user_tools_available(settings: Settings) -> bool:
    """Whether this deployment needs the person's short-lived MCP token after sign-in."""

    return planning_chat_available(settings) or global_risk_contributions_available(settings)


def data_inspector_available(settings: Settings) -> bool:
    """ADR-0006: the Admin data inspector runs only in local development.

    The source folder is mounted read-only by `deploy/compose.desktop.yml`. A server with the
    flag on and no folder is handled by the routes, which report that none is configured.
    """

    return settings.data_inspector_enabled and settings.grp_env == "dev"
