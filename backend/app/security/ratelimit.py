"""Fixed-window per-IP rate limiting backed by Redis.

Applied to unauthenticated endpoints (login, first-run setup) to slow
credential stuffing. The window is best-effort: if Redis is unreachable the
request is allowed rather than taking the API down with it.
"""

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.logs import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Dependency allowing ``times`` requests per ``seconds`` per client IP."""

    def __init__(self, times: int, seconds: int, scope: str) -> None:
        self.times = times
        self.seconds = seconds
        self.scope = scope

    async def __call__(self, request: Request) -> None:
        if get_settings().disable_rate_limits:
            return
        client_ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{self.scope}:{client_ip}"
        redis: Redis = request.app.state.redis
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, self.seconds)
        except RedisError:
            logger.warning("ratelimit.redis_unavailable", scope=self.scope)
            return
        if count > self.times:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests, slow down.",
            )
