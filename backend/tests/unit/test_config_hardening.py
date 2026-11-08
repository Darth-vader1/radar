import pytest
from pydantic import ValidationError

from app.core.config import Settings

SAFE_PROD = dict(
    ENVIRONMENT="production",
    DEBUG=False,
    SECRET_KEY="x" * 48,
    BACKEND_CORS_ORIGINS=["https://radar.example.com"],
    DATABASE_URL="postgresql+asyncpg://radar:s3cret@db:5432/radar",
)


def make(**overrides):
    # _env_file=None: ignore any local .env so the test only sees these values.
    return Settings(_env_file=None, **{**SAFE_PROD, **overrides})


def test_safe_production_config_loads():
    s = make()
    assert s.is_production
    assert s.cookie_secure is True
    assert s.public_registration_enabled is False


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"SECRET_KEY": "change_this_to_a_secure_random_secret_in_production_radar_2026_xyz"}, "SECRET_KEY"),
        ({"SECRET_KEY": "too-short"}, "SECRET_KEY"),
        ({"DEBUG": True}, "DEBUG"),
        ({"ENFORCE_SSRF_PROTECTION": False}, "SSRF"),
        ({"BACKEND_CORS_ORIGINS": ["http://localhost:3000"]}, "CORS"),
        ({"DATABASE_URL": "postgresql+asyncpg://radar_user:radar_secure_pass@db/radar_db"}, "DATABASE_URL"),
    ],
)
def test_unsafe_production_config_refused(overrides, message):
    with pytest.raises(ValidationError, match=message):
        make(**overrides)


def test_development_allows_defaults():
    s = Settings(_env_file=None, ENVIRONMENT="development")
    assert s.DEBUG is False  # safe default even in development
    assert s.public_registration_enabled is True
    assert s.cookie_secure is False


def test_registration_flag_overrides_environment_default():
    assert make(ALLOW_PUBLIC_REGISTRATION=True).public_registration_enabled is True


def test_list_settings_accept_comma_separated_env_values(monkeypatch):
    # Regression: pydantic-settings used to JSON-decode these and crash on "a,b" values.
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "https://radar.example.com, https://admin.radar.example.com")
    monkeypatch.setenv("ALLOWED_OUTBOUND_PORTS", "80,443,8443")
    s = Settings(_env_file=None)
    assert s.BACKEND_CORS_ORIGINS == ["https://radar.example.com", "https://admin.radar.example.com"]
    assert s.ALLOWED_OUTBOUND_PORTS == [80, 443, 8443]


def test_list_settings_still_accept_json(monkeypatch):
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", '["https://radar.example.com"]')
    assert Settings(_env_file=None).BACKEND_CORS_ORIGINS == ["https://radar.example.com"]
