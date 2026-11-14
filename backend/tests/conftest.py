import os
import sys

import pytest

# Ensure backend directory is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings


@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Sets test flags for fast and secure execution without live external side effects."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "ENFORCE_SSRF_PROTECTION", True)


@pytest.fixture(autouse=True)
def fresh_dns_cache():
    """Each test resolves hosts from scratch (the app caches DNS answers for 60 s)."""
    from app.core.security import clear_dns_cache

    clear_dns_cache()
    yield
    clear_dns_cache()
