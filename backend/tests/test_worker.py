"""Worker heartbeat and arq settings."""

import os
from datetime import datetime

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


async def test_heartbeat_writes_expiring_key(redis: Redis) -> None:
    returned = await heartbeat({"redis": redis})
    stored = await redis.get(HEARTBEAT_KEY)
    assert stored == returned
    datetime.fromisoformat(stored)  # valid ISO timestamp
    ttl = await redis.ttl(HEARTBEAT_KEY)
    assert 0 < ttl <= HEARTBEAT_TTL_SECONDS


async def test_startup_and_shutdown_hooks() -> None:
    await startup({})
    await shutdown({})


def test_worker_settings_wired() -> None:
    assert WorkerSettings.functions == []
    assert len(WorkerSettings.cron_jobs) == 1
    expected = RedisSettings.from_dsn(os.environ["BLINK_REDIS_URL"])
    assert WorkerSettings.redis_settings.host == expected.host
    assert WorkerSettings.redis_settings.port == expected.port
