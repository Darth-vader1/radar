from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness():
    return {"status": "ok", "service": "radar-api"}


@router.get("/ready")
async def readiness(db: AsyncSession = Depends(get_db)):
    checks = {
        "database": False,
        "redis": False,
    }

    # Check PostgreSQL
    try:
        result = await db.execute(text("SELECT 1"))
        if result.scalar() == 1:
            checks["database"] = True
    except Exception as e:
        checks["database_error"] = str(e)

    # Check Redis
    try:
        r = aioredis.from_url(settings.REDIS_URL, socket_timeout=2.0)
        pong = await r.ping()
        await r.aclose()
        if pong:
            checks["redis"] = True
    except Exception as e:
        checks["redis_error"] = str(e)

    is_ready = checks["database"] and checks["redis"]
    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=status_code,
        content={
            "ready": is_ready,
            "checks": checks,
            "environment": settings.ENVIRONMENT,
        }
    )
