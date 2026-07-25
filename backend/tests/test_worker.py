"""Worker heartbeat, startup/shutdown lifecycle, and arq settings."""

# arq ships no type stubs; WorkerSettings.functions/cron_jobs/redis_settings
# and arq.worker.Function's attributes all come back Unknown.
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false

import os
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from arq.connections import RedisSettings
from redis.asyncio import Redis

from app.worker.main import (
    HEARTBEAT_KEY,
    HEARTBEAT_TTL_SECONDS,
    WorkerSettings,
    heartbeat,
    shutdown,
    startup,
)
from app.worker.tasks.blink_sync import SYNC_JOB_NAME
from app.worker.tasks.download import DOWNLOAD_JOB_NAME


async def test_heartbeat_writes_expiring_key(redis: Redis) -> None:
    returned = await heartbeat({"redis": redis})
    stored = await redis.get(HEARTBEAT_KEY)
    assert stored == returned
    datetime.fromisoformat(stored)  # valid ISO timestamp
    ttl = await redis.ttl(HEARTBEAT_KEY)
    assert 0 < ttl <= HEARTBEAT_TTL_SECONDS


async def test_startup_creates_db_resources_and_kicks_off_sync() -> None:
    fake_redis = AsyncMock()
    ctx: dict[str, Any] = {"redis": fake_redis}

    await startup(ctx)

    assert "engine" in ctx
    assert "sessionmaker" in ctx
    fake_redis.enqueue_job.assert_awaited_once_with(SYNC_JOB_NAME)

    await ctx["engine"].dispose()


async def test_shutdown_disposes_the_engine() -> None:
    fake_engine = AsyncMock()
    await shutdown({"engine": fake_engine})
    fake_engine.dispose.assert_awaited_once()


def test_worker_settings_wired() -> None:
    names = {fn.name for fn in WorkerSettings.functions}
    assert names == {SYNC_JOB_NAME, DOWNLOAD_JOB_NAME}
    assert len(WorkerSettings.cron_jobs) == 1
    expected = RedisSettings.from_dsn(os.environ["BLINK_REDIS_URL"])
    assert WorkerSettings.redis_settings.host == expected.host
    assert WorkerSettings.redis_settings.port == expected.port


@pytest.mark.parametrize("job_name", [SYNC_JOB_NAME, DOWNLOAD_JOB_NAME])
def test_worker_functions_have_retry_limits(job_name: str) -> None:
    fn = next(f for f in WorkerSettings.functions if f.name == job_name)
    assert fn.max_tries is not None
