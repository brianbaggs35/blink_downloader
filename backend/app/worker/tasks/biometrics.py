"""Background biometrics model download: the slow part of Settings'
"Verify / download model" action, run as a real worker job so navigating
away from Settings can't interrupt it - see app.biometrics.service's
download_biometrics_model docstring for the raise/catch split this mirrors
from app.worker.tasks.sync_module.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.biometrics.models import ModelDownloadStatus
from app.biometrics.recognition import ModelLoadError
from app.biometrics.service import download_biometrics_model, get_biometrics_settings
from app.config import get_settings
from app.logs import get_logger

logger = get_logger(__name__)

DOWNLOAD_MODEL_JOB_NAME = "download_biometrics_model"


async def download_biometrics_model_job(ctx: dict[Any, Any]) -> str:
    settings = get_settings()
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    async with sessionmaker() as session:
        biometrics_settings = await get_biometrics_settings(session)
        # Postgres holds a SELECT's ACCESS SHARE table lock until the
        # transaction actually commits, not just until the statement
        # finishes - without this commit, that lock would sit open for the
        # full duration of download_biometrics_model's slow, thread-pooled
        # model load below, which can collide with an e2e test reset's
        # TRUNCATE (ACCESS EXCLUSIVE conflicts with every other lock mode).
        # Safe to keep using biometrics_settings afterward: sessionmaker is
        # built with expire_on_commit=False. Mirrors the commit-before-the-
        # slow-call pattern app.testing.seed's own reset-time re-verify call
        # to this same function already uses.
        await session.commit()
        try:
            await download_biometrics_model(
                session, biometrics_settings, settings.biometrics_model_cache_dir
            )
        except ModelLoadError as exc:
            biometrics_settings.model_download_status = ModelDownloadStatus.ERROR
            biometrics_settings.model_download_error = str(exc)
            await session.commit()
            logger.warning("biometrics.model_download_failed", error=str(exc))
            return f"failed: {exc}"
        logger.info(
            "biometrics.model_download_completed",
            model_pack=biometrics_settings.model_pack.value,
            providers=biometrics_settings.model_download_providers,
        )
        return "ok"
