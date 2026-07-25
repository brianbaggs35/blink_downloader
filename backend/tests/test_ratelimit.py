"""Rate limiter: allows the window, rejects the overflow, fails open."""

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient
from redis.exceptions import RedisError
from starlette.requests import Request

from app.security.ratelimit import RateLimiter


def _request(app: FastAPI, client_ip: str | None) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "app": app,
        "client": (client_ip, 12345) if client_ip else None,
        "headers": [],
        "method": "POST",
        "path": "/",
        "query_string": b"",
    }
    return Request(scope)


async def test_allows_within_window_then_rejects(client: AsyncClient, app: FastAPI) -> None:
    limiter = RateLimiter(times=3, seconds=60, scope="test")
    request = _request(app, "10.0.0.1")
    for _ in range(3):
        await limiter(request)
    with pytest.raises(HTTPException) as exc_info:
        await limiter(request)
    assert exc_info.value.status_code == 429


async def test_windows_are_per_ip(client: AsyncClient, app: FastAPI) -> None:
    limiter = RateLimiter(times=1, seconds=60, scope="per-ip")
    await limiter(_request(app, "10.0.0.2"))
    await limiter(_request(app, "10.0.0.3"))  # different IP: not throttled


async def test_missing_client_uses_unknown_bucket(client: AsyncClient, app: FastAPI) -> None:
    limiter = RateLimiter(times=1, seconds=60, scope="anon")
    await limiter(_request(app, None))
    with pytest.raises(HTTPException):
        await limiter(_request(app, None))


async def test_fails_open_when_redis_unavailable(client: AsyncClient, app: FastAPI) -> None:
    class BrokenRedis:
        async def incr(self, _key: str) -> int:
            msg = "down"
            raise RedisError(msg)

    original = app.state.redis
    app.state.redis = BrokenRedis()
    try:
        limiter = RateLimiter(times=1, seconds=60, scope="broken")
        request = _request(app, "10.0.0.4")
        await limiter(request)
        await limiter(request)  # would raise if the limiter were enforcing
    finally:
        app.state.redis = original
