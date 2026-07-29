"""arq worker: heartbeat, Blink sync, and clip downloads.

Run with: ``arq app.worker.main.WorkerSettings``
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.worker import func

from app.config import get_settings
from app.db import build_engine, build_sessionmaker
from app.logs import configure_logging, get_logger
from app.worker.tasks.alerts import send_alert
from app.worker.tasks.analyze import analyze_clip
from app.worker.tasks.archive import (
    ARCHIVE_CLIP_JOB_NAME,
    AUTO_ARCHIVE_CLIP_JOB_NAME,
    RESTORE_CLIP_JOB_NAME,
    archive_clip_job,
    auto_archive_clip_job,
    restore_clip_job,
)
from app.worker.tasks.blink_sync import SYNC_JOB_NAME, sync_blink_account
from app.worker.tasks.download import download_clip
from app.worker.tasks.sync_module import (
    DELETE_LOCAL_ITEM_JOB_NAME,
    DOWNLOAD_LOCAL_ITEM_JOB_NAME,
    REFRESH_LOCAL_STORAGE_JOB_NAME,
    delete_sync_module_local_item_job,
    download_sync_module_local_item_job,
    refresh_sync_module_local_storage_job,
)

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
    settings = get_settings()
    configure_logging(settings)
    engine = build_engine(settings.database_url)
    ctx["engine"] = engine
    ctx["sessionmaker"] = build_sessionmaker(engine)
    logger.info("worker.started")
    if not settings.disable_blink_network_calls:
        # Self-reschedules at the end of every run (see blink_sync.py) so its
        # cadence follows BLINK_SYNC_INTERVAL_SECONDS, which arq's
        # calendar-style cron can't express directly.
        await ctx["redis"].enqueue_job(SYNC_JOB_NAME)


async def shutdown(ctx: dict[Any, Any]) -> None:
    await ctx["engine"].dispose()
    logger.info("worker.stopped")


class WorkerSettings:
    """Attribute namespace consumed by `arq app.worker.main.WorkerSettings`."""

    functions: ClassVar[list[Any]] = [
        func(sync_blink_account, name=SYNC_JOB_NAME, max_tries=1, timeout=120),
        func(download_clip, max_tries=3, timeout=120),
        func(analyze_clip, max_tries=2, timeout=240),
        func(send_alert, max_tries=2, timeout=30),
        func(archive_clip_job, name=ARCHIVE_CLIP_JOB_NAME, max_tries=2, timeout=300),
        func(auto_archive_clip_job, name=AUTO_ARCHIVE_CLIP_JOB_NAME, max_tries=2, timeout=300),
        func(restore_clip_job, name=RESTORE_CLIP_JOB_NAME, max_tries=2, timeout=300),
        func(
            refresh_sync_module_local_storage_job,
            name=REFRESH_LOCAL_STORAGE_JOB_NAME,
            max_tries=2,
            timeout=180,
        ),
        func(
            download_sync_module_local_item_job,
            name=DOWNLOAD_LOCAL_ITEM_JOB_NAME,
            max_tries=2,
            timeout=180,
        ),
        func(
            delete_sync_module_local_item_job,
            name=DELETE_LOCAL_ITEM_JOB_NAME,
            max_tries=2,
            timeout=60,
        ),
    ]
    cron_jobs: ClassVar[list[Any]] = [cron(heartbeat, second=0, run_at_startup=True)]
    on_startup = staticmethod(startup)
    on_shutdown = staticmethod(shutdown)
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
