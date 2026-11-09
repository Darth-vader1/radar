"""
Celery worker liveness via Redis keys.

Each worker process refreshes `radar:worker:heartbeat:<hostname>` every INTERVAL seconds
with a TTL of TTL seconds. A worker that dies or hangs simply stops refreshing and its
key expires, so "live workers" = number of keys present. Cheaper and more reliable than
`celery inspect ping` (no broadcast round-trip), and readable from the API.
"""
import logging
import threading
import time
from typing import Optional

import redis
import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger("radar.heartbeat")

KEY_PREFIX = "radar:worker:heartbeat:"
INTERVAL_SECONDS = 30
TTL_SECONDS = 90

_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def _beat(hostname: str, redis_url: str) -> None:
    client = redis.Redis.from_url(redis_url, socket_timeout=3.0, socket_connect_timeout=3.0)
    key = f"{KEY_PREFIX}{hostname}"
    while not _stop.is_set():
        try:
            client.set(key, str(int(time.time())), ex=TTL_SECONDS)
        except Exception as exc:  # Redis blip: try again next interval
            logger.warning("Worker heartbeat write failed: %s", type(exc).__name__)
        _stop.wait(INTERVAL_SECONDS)
    try:
        client.delete(key)  # clean shutdown: don't count this worker for another TTL
    except Exception:
        pass


def start_worker_heartbeat(hostname: str, redis_url: Optional[str] = None) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_beat, args=(hostname, redis_url or settings.REDIS_URL), name="radar-heartbeat", daemon=True
    )
    _thread.start()
    logger.info("Worker heartbeat started for %s", hostname)


def stop_worker_heartbeat(timeout: float = 5.0) -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout)
    _thread = None


async def count_live_workers(redis_url: Optional[str] = None) -> int:
    client = aioredis.from_url(redis_url or settings.REDIS_URL, socket_timeout=2.0, socket_connect_timeout=2.0)
    try:
        count = 0
        async for _ in client.scan_iter(match=f"{KEY_PREFIX}*", count=100):
            count += 1
        return count
    finally:
        await client.aclose()
