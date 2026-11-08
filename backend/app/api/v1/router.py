from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.businesses import router as businesses_router
from app.api.v1.events import router as events_router
from app.api.v1.health import router as health_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.sources import router as sources_router
from app.api.v1.tasks import router as tasks_router

api_v1_router = APIRouter()

api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(sources_router)
api_v1_router.include_router(tasks_router)
api_v1_router.include_router(businesses_router)
api_v1_router.include_router(jobs_router)
api_v1_router.include_router(events_router)
