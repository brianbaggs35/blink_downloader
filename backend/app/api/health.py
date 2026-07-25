"""Liveness/readiness endpoint used by container healthchecks and the Status tab."""

# redis-py 5.x (capped by arq) ships partial type annotations.
# pyright: reportUnknownMemberType=false

from typing import Annotated, Literal

from fastapi import Depends, Request, Response, status
from fastapi.routing import APIRouter
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db import get_session
from app.logs import get_logger
from app.worker.main import HEARTBEAT_KEY

logger = get_logger(__name__)

router = APIRouter()

ComponentState = Literal["ok", "error", "unknown"]


class HealthReport(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: ComponentState
    redis: ComponentState
    worker: ComponentState


@router.get("/health", response_model=HealthReport)
async def health(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealthReport:
    database: ComponentState = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health.database_error")
        database = "error"

    redis_state: ComponentState = "ok"
    worker: ComponentState = "unknown"
    redis: Redis = request.app.state.redis
    try:
        await redis.ping()
        if await redis.exists(HEARTBEAT_KEY):
            worker = "ok"
    except Exception:
        logger.exception("health.redis_error")
        redis_state = "error"

    overall: Literal["ok", "degraded"] = "ok"
    if database != "ok" or redis_state != "ok":
        overall = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthReport(
        status=overall,
        version=__version__,
        database=database,
        redis=redis_state,
        worker=worker,
    )
