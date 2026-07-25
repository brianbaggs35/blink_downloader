"""arq worker: cron heartbeat now; Blink sync, downloads, and the AI pipeline
land here as their features arrive.

Run with: ``arq app.worker.main.WorkerSettings``
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.logs import configure_logging, get_logger

logger = get_logger(__name__)

HEARTBEAT_KEY = "blink:worker:heartbeat"
HEARTBEAT_TTL_SECONDS = 180


async def heartbeat(ctx: dict[Any, Any]) -> str:
    """Proves worker liveness to the health endpoint / Status tab."""
    now = datetime.now(UTC).isoformat()
    await ctx["redis"].set(HEARTBEAT_KEY, now, ex=HEARTBEAT_TTL_SECONDS)
    logger.debug("worker.heartbeat", at=now)
    return now


async def startup(ctx: dict[Any, Any]) -> None:
    configure_logging(get_settings())
    logger.info("worker.started")


async def shutdown(ctx: dict[Any, Any]) -> None:
    logger.info("worker.stopped")


class WorkerSettings:
    """Attribute namespace consumed by `arq app.worker.main.WorkerSettings`."""

    functions: ClassVar[list[Any]] = []
    cron_jobs: ClassVar[list[Any]] = [cron(heartbeat, second=0, run_at_startup=True)]
    on_startup = staticmethod(startup)
    on_shutdown = staticmethod(shutdown)
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
