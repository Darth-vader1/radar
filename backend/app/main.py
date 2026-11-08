from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.logging import logger, setup_logging
from app.core.security import SSRFValidationError
from app.modules.adapters_loader import load_adapters


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
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


@app.get("/", tags=["Root"])
async def root():
    return {
        "platform": settings.PROJECT_NAME,
        "version": "1.0.0",
        "status": "operational",
        "docs": f"{settings.API_V1_PREFIX}/docs" if settings.DEBUG else "disabled",
    }
