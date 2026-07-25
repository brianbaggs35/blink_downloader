"""FastAPI application factory."""

# redis-py 5.x (capped by arq) ships partial type annotations.
# pyright: reportUnknownMemberType=false

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app import __version__
from app.api import api_router
from app.config import Settings, get_settings
from app.db import build_engine, build_sessionmaker
from app.logs import configure_logging, get_logger
from app.security.headers import SecurityHeadersMiddleware

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    configure_logging(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        engine = build_engine(config.database_url)
        app.state.engine = engine
        app.state.sessionmaker = build_sessionmaker(engine)
        app.state.redis = Redis.from_url(config.redis_url)
        logger.info("app.started", environment=config.environment, version=__version__)
        yield
        await app.state.redis.aclose()
        await engine.dispose()
        logger.info("app.stopped")

    in_production = config.environment == "production"
    app = FastAPI(
        title="Blink AI Security Platform",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if in_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if in_production else "/api/openapi.json",
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(api_router)
    return app


app = create_app()
