"""Health endpoint: component states and degraded status codes."""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db import get_session
from app.worker.main import HEARTBEAT_KEY


async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["redis"] == "ok"
    assert body["worker"] == "unknown"
    assert body["version"]


async def test_health_reports_worker_when_heartbeat_present(
    client: AsyncClient, app: FastAPI
) -> None:
    await app.state.redis.set(HEARTBEAT_KEY, "2026-07-24T00:00:00+00:00", ex=60)
    response = await client.get("/api/health")
    assert response.json()["worker"] == "ok"


async def test_health_degraded_when_database_down(client: AsyncClient, app: FastAPI) -> None:
    class BrokenSession:
        async def execute(self, *_args: Any, **_kwargs: Any) -> None:
            msg = "connection refused"
            raise ConnectionError(msg)

    async def broken_session() -> Any:
        yield BrokenSession()

    app.dependency_overrides[get_session] = broken_session
    try:
        response = await client.get("/api/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "error"


async def test_health_degraded_when_redis_down(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_ping() -> None:
        msg = "redis down"
        raise ConnectionError(msg)

    monkeypatch.setattr(app.state.redis, "ping", broken_ping)
    response = await client.get("/api/health")
    assert response.status_code == 503
    body = response.json()
    assert body["redis"] == "error"
    assert body["worker"] == "unknown"
