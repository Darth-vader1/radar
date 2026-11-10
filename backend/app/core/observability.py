"""
Sentry error tracking (opt-in: does nothing unless SENTRY_DSN is set).

PII stays out: no request bodies, cookies, auth headers or user IPs are sent
(send_default_pii=False plus an explicit scrub). Events are tagged with the log
correlation context (request_id, run_id, source, task) so a Sentry issue can be matched
to its log lines.
"""
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger("radar.observability")

_SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key", "set-cookie", "proxy-authorization"}
_initialized = False


def _before_send(event: Any, hint: Any) -> Any:
    from app.core.logging import get_context

    tags = event.setdefault("tags", {})
    for key, value in get_context().items():
        tags.setdefault(key, value)

    request = event.get("request") or {}
    headers = request.get("headers")
    if isinstance(headers, dict):
        request["headers"] = {
            k: ("[Filtered]" if k.lower() in _SENSITIVE_HEADERS else v) for k, v in headers.items()
        }
    request.pop("cookies", None)
    request.pop("data", None)
    return event


def init_sentry(component: str) -> bool:
    """Initialises Sentry once per process. Returns True if enabled."""
    global _initialized
    if _initialized or not settings.SENTRY_DSN:
        return _initialized

    import sentry_sdk
    from sentry_sdk.integrations import Integration
    from sentry_sdk.integrations.logging import LoggingIntegration

    integrations: list[Integration] = [LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)]
    if component == "worker":
        from sentry_sdk.integrations.celery import CeleryIntegration

        integrations.append(CeleryIntegration(monitor_beat_tasks=False))

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        release=settings.APP_RELEASE,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,
        max_request_body_size="never",
        integrations=integrations,
        before_send=_before_send,
    )
    sentry_sdk.set_tag("component", component)
    _initialized = True
    logger.info("Sentry error tracking enabled (component=%s, environment=%s)", component, settings.ENVIRONMENT)
    return True
