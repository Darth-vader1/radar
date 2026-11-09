import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.heartbeat import count_live_workers

logger = logging.getLogger("radar.health")
router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness():
    """The process is up. Used by container health checks; never touches dependencies."""
    return {"status": "ok", "service": "radar-api"}


async def _ping_redis(url: str) -> bool:
    client = aioredis.from_url(url, socket_timeout=2.0, socket_connect_timeout=2.0)
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()


@router.get("/ready")
async def readiness(db: AsyncSession = Depends(get_db)):
    """
    Whether this API instance can serve traffic: database, cache and task broker reachable.
    Worker liveness is reported but does not fail readiness (the API still serves reads and
    queues runs without a worker). Failure details go to the server log, not the response.
    """
    checks: dict[str, object] = {"database": False, "redis": False, "broker": False}

    try:
        checks["database"] = (await db.execute(text("SELECT 1"))).scalar() == 1
    except Exception:
        logger.exception("Readiness: database check failed")

    try:
        checks["redis"] = await _ping_redis(settings.REDIS_URL)
    except Exception:
        logger.exception("Readiness: redis check failed")

    try:
        checks["broker"] = await _ping_redis(settings.CELERY_BROKER_URL)
    except Exception:
        logger.exception("Readiness: broker check failed")

    try:
        checks["workers_alive"] = await count_live_workers()
    except Exception:
        logger.warning("Readiness: could not count live workers")
        checks["workers_alive"] = None

    is_ready = bool(checks["database"] and checks["redis"] and checks["broker"])
    return JSONResponse(
        status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"ready": is_ready, "checks": checks, "environment": settings.ENVIRONMENT},
    )
