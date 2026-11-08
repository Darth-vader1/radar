from celery import Celery
from celery.signals import worker_process_init

from app.core.config import settings
from app.modules.adapters_loader import load_adapters

celery_app = Celery(
    "radar_workers",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["workers.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.PIPELINE_TIME_LIMIT_SECONDS,
    task_soft_time_limit=settings.PIPELINE_SOFT_TIME_LIMIT_SECONDS,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    # Acknowledge only after the task finishes, and put it back on the queue if the worker
    # process dies mid-task, so a crash doesn't silently lose a run.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Redis redelivers unacknowledged tasks after this; it must exceed the hard time limit
    # or long runs would be delivered twice.
    broker_transport_options={"visibility_timeout": settings.PIPELINE_TIME_LIMIT_SECONDS + 1800},
    # Fail fast when publishing if the broker is down (the API reports 503 instead of hanging).
    broker_connection_timeout=3,
    broker_connection_retry_on_startup=True,
    result_expires=24 * 3600,
    beat_schedule={
        "dispatch-scheduled-sources": {"task": "tasks.dispatch_scheduled_sources", "schedule": 60.0},
        "reap-stale-runs": {"task": "tasks.reap_stale_runs", "schedule": 300.0},
        "refresh-event-statuses": {"task": "tasks.refresh_event_statuses", "schedule": 3600.0},
    },
)

# Register source adapters in every process that may execute pipelines.
# Module-level call covers the main process and solo/threads pools;
# the signal covers prefork children if the registry was not inherited.
load_adapters()


@worker_process_init.connect
def _load_adapters_in_child(**_kwargs) -> None:
    load_adapters()
