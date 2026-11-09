import logging
import re
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.v1.router import api_v1_router
from app.core import metrics
from app.core.config import settings
from app.core.logging import bind_context, logger, reset_context, setup_logging
from app.core.observability import init_sentry
from app.core.security import SSRFValidationError
from app.modules.adapters_loader import load_adapters

# Configure logging and error tracking at import time so start-up failures are captured too.
setup_logging()
init_sentry("api")

access_logger = logging.getLogger("radar.access")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing RADAR Web Intelligence Platform backend (env=%s)...", settings.ENVIRONMENT)
    # Ensure all discovery adapters are registered (importing the packages alone does not).
    load_adapters()
    yield
    logger.info("Shutting down RADAR backend cleanly.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Unified Web Intelligence & Discovery Platform (BusinessRadar, JobRadar, EventRadar)",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

# CORS Middleware
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    headers = response.headers
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "no-referrer")
    headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if not request.url.path.endswith(("/docs", "/redoc")) and "/docs/" not in request.url.path:
        # JSON API: nothing should ever be rendered or framed from these responses.
        headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if request.url.path.startswith(f"{settings.API_V1_PREFIX}/auth"):
        headers.setdefault("Cache-Control", "no-store")
    if settings.is_production:
        headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return response


@app.middleware("http")
async def request_context(request: Request, call_next):
    """
    Outermost middleware: assigns a request id (honouring a well-formed incoming
    X-Request-ID from the proxy), binds it to the log context, records HTTP metrics and
    writes one access log line per request.
    """
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
    token = bind_context(request_id=request_id)
    start = metrics.monotonic()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        elapsed = metrics.monotonic() - start
        route = metrics.route_label(request.scope)
        if settings.METRICS_ENABLED and route != "/metrics":
            metrics.observe_request(request.method, route, status_code, elapsed)
        if not (route == "/api/v1/health/live" and status_code == 200):  # skip probe noise
            access_logger.info(
                "%s %s %s %.1fms", request.method, request.url.path, status_code, elapsed * 1000,
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_route": route,
                    "http_status": status_code,
                    "duration_ms": round(elapsed * 1000, 1),
                    "client_ip": request.client.host if request.client else None,
                },
            )
        reset_context(token)


# Exception handler for SSRF security violations
@app.exception_handler(SSRFValidationError)
async def ssrf_exception_handler(request: Request, exc: SSRFValidationError):
    logger.warning("SSRF Security Violation blocked on %s: %s", request.url.path, str(exc))
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        # Details (resolved IPs, internal hostnames) stay in the server log only.
        content={"detail": "Outbound request rejected by security policy."}
    )


# Mount versioned API
app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics(authorization: str | None = Header(None)):
    """
    Prometheus scrape endpoint. Served outside /api so the public proxy never routes it;
    scrape it on the internal network (backend:8000/metrics). Set METRICS_TOKEN to also
    require a bearer token.
    """
    if not settings.METRICS_ENABLED:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    if not metrics.check_metrics_token(authorization):
        return Response(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"})
    body, content_type = await metrics.render_metrics()
    return Response(content=body, media_type=content_type)


@app.get("/", tags=["Root"])
async def root():
    return {
        "platform": settings.PROJECT_NAME,
        "version": "1.0.0",
        "status": "operational",
        "docs": f"{settings.API_V1_PREFIX}/docs" if settings.DEBUG else "disabled",
    }
