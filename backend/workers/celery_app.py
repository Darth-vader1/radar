from celery import Celery
from celery.signals import (
    beat_init,
    celeryd_init,
    setup_logging as celery_setup_logging,
    task_postrun,
    task_prerun,
    worker_process_init,
    worker_ready,
    worker_shutdown,
)

from app.core.config import settings
from app.core.heartbeat import start_worker_heartbeat, stop_worker_heartbeat
from app.core.logging import bind_context, reset_context, setup_logging
from app.core.observability import init_sentry
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
    # Use our JSON/text log formatting (see the setup_logging signal below).
    worker_hijack_root_logger=False,
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


# --- Observability -------------------------------------------------------------

@celery_setup_logging.connect
def _configure_logging(**_kwargs) -> None:
    # Connecting this signal stops Celery from installing its own log format.
    setup_logging()


@celeryd_init.connect
def _init_worker_observability(**_kwargs) -> None:
    init_sentry("worker")


@worker_process_init.connect
def _init_child_observability(**_kwargs) -> None:
    init_sentry("worker")


@beat_init.connect
def _init_beat_observability(**_kwargs) -> None:
    setup_logging()
    init_sentry("beat")


@worker_ready.connect
def _start_heartbeat(sender=None, **_kwargs) -> None:
    start_worker_heartbeat(getattr(sender, "hostname", None) or "unknown-worker")


@worker_shutdown.connect
def _stop_heartbeat(**_kwargs) -> None:
    stop_worker_heartbeat()


_task_log_tokens: dict = {}


@task_prerun.connect
def _bind_task_context(task_id=None, task=None, **_kwargs) -> None:
    _task_log_tokens[task_id] = bind_context(task_id=task_id, task_name=getattr(task, "name", None))


@task_postrun.connect
def _clear_task_context(task_id=None, **_kwargs) -> None:
    token = _task_log_tokens.pop(task_id, None)
    if token is not None:
        try:
            reset_context(token)
        except ValueError:
            pass  # bound in a different context (e.g. eager mode); nothing to undo
