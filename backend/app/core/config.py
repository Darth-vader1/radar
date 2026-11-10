from typing import Annotated, List, Optional, Union

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[".env", "../.env"],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    PROJECT_NAME: str = "RADAR Web Intelligence Platform"
    API_V1_PREFIX: str = "/api/v1"

    # Security & JWT
    SECRET_KEY: str = "change_this_to_a_secure_random_secret_in_production_radar_2026_xyz"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Registration & sessions
    # None = allowed outside production, disabled in production unless set explicitly.
    ALLOW_PUBLIC_REGISTRATION: Optional[bool] = None
    # Auth cookies for the web app. COOKIE_SECURE=None -> Secure flag only in production.
    COOKIE_SECURE: Optional[bool] = None
    COOKIE_SAMESITE: str = "lax"
    ACCESS_COOKIE_NAME: str = "radar_access"
    REFRESH_COOKIE_NAME: str = "radar_refresh"
    # Carries no secret: lets the web app's edge middleware know a session exists, since the
    # refresh cookie is path-scoped to the auth routes and never sent with page requests.
    SESSION_HINT_COOKIE_NAME: str = "radar_session"

    # Abuse protection
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 5
    REGISTER_RATE_LIMIT_PER_HOUR: int = 5
    TRUST_PROXY_HEADERS: bool = False  # honour X-Forwarded-For only behind a trusted proxy

    # CORS
    BACKEND_CORS_ORIGINS: Annotated[List[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
    ]

    # Database URLs (Using 127.0.0.1:5433 to avoid collision with any existing local Windows PostgreSQL service)
    DATABASE_URL: str = "postgresql+asyncpg://radar_user:radar_secure_pass@127.0.0.1:5433/radar_db"
    DATABASE_SYNC_URL: str = "postgresql://radar_user:radar_secure_pass@127.0.0.1:5433/radar_db"

    # Redis & Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # SSRF & Scraping Politeness
    ENFORCE_SSRF_PROTECTION: bool = True
    ALLOWED_OUTBOUND_PORTS: Annotated[List[int], NoDecode] = [80, 443]
    HTTP_USER_AGENT: str = "RadarBot/1.0 (+https://radar-intel.local/bot; bot@radar-intel.local)"
    MAX_REDIRECT_HOPS: int = 5
    DEFAULT_REQUEST_TIMEOUT: float = 20.0
    MAX_RESPONSE_BYTES: int = 5 * 1024 * 1024  # hard cap on any fetched body

    # Observability
    LOG_FORMAT: Optional[str] = None   # "json" | "text"; default: json in production, text otherwise
    LOG_LEVEL: Optional[str] = None    # default: DEBUG when DEBUG=true, else INFO
    METRICS_ENABLED: bool = True
    METRICS_TOKEN: Optional[str] = None  # if set, GET /metrics requires "Authorization: Bearer <token>"
    SENTRY_DSN: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    APP_RELEASE: Optional[str] = None  # e.g. git SHA; tagged on Sentry events and the metrics build info

    # Job execution
    PIPELINE_SOFT_TIME_LIMIT_SECONDS: int = 1500  # raises inside the task so it can record FAILED
    PIPELINE_TIME_LIMIT_SECONDS: int = 1800       # hard kill; the reaper cleans up after it
    QUEUED_RUN_STALE_AFTER_SECONDS: int = 6 * 3600  # QUEUED this long = never picked up
    TASK_DISPATCH_TIMEOUT_SECONDS: float = 5.0

    @field_validator("ALLOWED_OUTBOUND_PORTS", mode="before")
    @classmethod
    def assemble_allowed_ports(cls, v: Union[str, List[int]]) -> List[int]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [int(p.strip()) for p in v.split(",") if p.strip()]
        return v

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # AI Configuration
    AI_ENABLED: bool = False
    DEFAULT_AI_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    LOCAL_LLM_BASE_URL: str = "http://localhost:11434/v1"
    LOCAL_LLM_MODEL: str = "llama3.2"

    # Optional 3rd Party API keys
    GOOGLE_PLACES_API_KEY: str | None = None
    WEB_SEARCH_API_KEY: str | None = None
    GOOGLE_CSE_ID: str | None = None
    HUNTER_API_KEY: str | None = None
    KAGGLE_USERNAME: str | None = None
    KAGGLE_KEY: str | None = None
    EVENTBRITE_PRIVATE_TOKEN: str | None = None

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in ("production", "prod")

    @property
    def public_registration_enabled(self) -> bool:
        if self.ALLOW_PUBLIC_REGISTRATION is None:
            return not self.is_production
        return self.ALLOW_PUBLIC_REGISTRATION

    @property
    def cookie_secure(self) -> bool:
        return self.is_production if self.COOKIE_SECURE is None else self.COOKIE_SECURE

    @model_validator(mode="after")
    def _refuse_unsafe_production_config(self) -> "Settings":
        if not self.is_production:
            return self
        problems = []
        if self.SECRET_KEY in _KNOWN_DEFAULT_SECRETS or len(self.SECRET_KEY) < 32:
            problems.append("SECRET_KEY must be a unique random value of at least 32 characters")
        if self.DEBUG:
            problems.append("DEBUG must be false")
        if not self.ENFORCE_SSRF_PROTECTION:
            problems.append("ENFORCE_SSRF_PROTECTION must be true")
        local_origins = [o for o in self.BACKEND_CORS_ORIGINS if "localhost" in o or "127.0.0.1" in o]
        if local_origins:
            problems.append(f"BACKEND_CORS_ORIGINS must not include local origins {local_origins}")
        if "radar_secure_pass" in self.DATABASE_URL:
            problems.append("DATABASE_URL uses the default development password")
        if problems:
            raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self


# Secrets that have shipped in this repo's defaults/examples and must never be used in production.
_KNOWN_DEFAULT_SECRETS = {
    "change_this_to_a_secure_random_secret_in_production_radar_2026_xyz",
    "radar_dev_super_secret_key_32bytes_min_2026",
}

settings = Settings()
