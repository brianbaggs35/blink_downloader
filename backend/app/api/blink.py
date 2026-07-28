"""Blink account linking and status.

Linking is superuser-only and rate-limited; status is visible to any signed-in
household member so the Status/Settings pages can show it without granting
account-management rights.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.linker import (
    BlinkConnectionError,
    BlinkInvalidCodeError,
    BlinkInvalidCredentialsError,
    BlinkLinker,
    BlinkLinkSessionExpiredError,
)
from app.blink.models import BlinkAccount, Camera, Clip
from app.blink.schemas import (
    BlinkLinkRequest,
    BlinkLinkResponse,
    BlinkStatusResponse,
    BlinkVerifyRequest,
    DailyClipCount,
)
from app.config import get_settings
from app.db import get_session
from app.logs import get_logger
from app.security.crypto import SecretBox
from app.security.ratelimit import RateLimiter
from app.settings.service import resolve_storage_dir
from app.storage.service import StorageError, get_clip_storage
from app.users.auth import current_active_user, current_superuser
from app.worker.tasks.blink_sync import SYNC_JOB_NAME

logger = get_logger(__name__)

router = APIRouter(prefix="/blink", tags=["blink"])

blink_rate_limit = RateLimiter(times=5, seconds=60, scope="blink-link")

STATUS_DAILY_HISTORY_DAYS = 7


def get_blink_linker(request: Request) -> BlinkLinker:
    return request.app.state.blink_linker


async def _account_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(BlinkAccount))).scalar_one()


async def _clip_stats(
    session: AsyncSession, account_id: uuid.UUID
) -> tuple[int, list[DailyClipCount]]:
    """Total clip count plus a fixed-width, zero-filled daily count for the
    last STATUS_DAILY_HISTORY_DAYS days (oldest first, today last) - for the
    Status page's at-a-glance activity trend."""
    total = (
        await session.execute(
            select(func.count())
            .select_from(Clip)
            .join(Camera, Camera.id == Clip.camera_id)
            .where(Camera.blink_account_id == account_id)
        )
    ).scalar_one()

    today = datetime.now(UTC).date()
    start = today - timedelta(days=STATUS_DAILY_HISTORY_DAYS - 1)
    rows = await session.execute(
        select(func.date(Clip.recorded_at), func.count())
        .join(Camera, Camera.id == Clip.camera_id)
        .where(Camera.blink_account_id == account_id, Clip.recorded_at >= start)
        .group_by(func.date(Clip.recorded_at))
    )
    counts_by_day = {str(day): count for day, count in rows}
    daily = [
        DailyClipCount(
            date=str(start + timedelta(days=offset)),
            count=counts_by_day.get(str(start + timedelta(days=offset)), 0),
        )
        for offset in range(STATUS_DAILY_HISTORY_DAYS)
    ]
    return total, daily


async def _persist_new_account(
    session: AsyncSession, username: str, password: str, token_data: dict[str, object]
) -> BlinkAccount:
    box = SecretBox(get_settings().encryption_key)
    account = BlinkAccount(
        encrypted_username=box.encrypt(username),
        encrypted_password=box.encrypt(password),
        encrypted_token_data=box.encrypt(json.dumps(token_data)),
    )
    session.add(account)
    await session.commit()
    return account


@router.post("/link", response_model=BlinkLinkResponse, dependencies=[Depends(blink_rate_limit)])
async def link_account(
    payload: BlinkLinkRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    linker: Annotated[BlinkLinker, Depends(get_blink_linker)],
    _user: Annotated[object, Depends(current_superuser)],
) -> BlinkLinkResponse:
    if await _account_count(session) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A Blink account is already linked. Unlink it first.",
        )

    try:
        outcome = await linker.start_link(payload.username, payload.password)
    except BlinkInvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BlinkConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    if outcome.verification_required:
        return BlinkLinkResponse(
            status="verification_required", link_session_id=outcome.link_session_id
        )

    if outcome.token_data is None:  # pragma: no cover — LinkOutcome's contract guarantees this
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected linking failure.",
        )
    await _persist_new_account(session, payload.username, payload.password, outcome.token_data)
    logger.info("blink.account_linked")
    return BlinkLinkResponse(status="linked")


@router.post("/verify", response_model=BlinkLinkResponse, dependencies=[Depends(blink_rate_limit)])
async def verify_account(
    payload: BlinkVerifyRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    linker: Annotated[BlinkLinker, Depends(get_blink_linker)],
    _user: Annotated[object, Depends(current_superuser)],
) -> BlinkLinkResponse:
    credentials = linker.pending_credentials(payload.link_session_id)
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This verification session has expired. Start the link again.",
        )
    username, password = credentials

    try:
        token_data = await linker.complete_2fa(payload.link_session_id, payload.code)
    except BlinkInvalidCodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BlinkLinkSessionExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    except BlinkConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    await _persist_new_account(session, username, password, token_data)
    logger.info("blink.account_linked", via="2fa")
    return BlinkLinkResponse(status="linked")


@router.get("/status", response_model=BlinkStatusResponse)
async def account_status(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> BlinkStatusResponse:
    account = (await session.execute(select(BlinkAccount))).scalars().first()
    if account is None:
        return BlinkStatusResponse(linked=False)
    camera_count = (
        await session.execute(
            select(func.count()).select_from(Camera).where(Camera.blink_account_id == account.id)
        )
    ).scalar_one()
    network_ids = (
        (
            await session.execute(
                select(Camera.blink_network_id)
                .where(Camera.blink_account_id == account.id)
                .distinct()
                .order_by(Camera.blink_network_id)
            )
        )
        .scalars()
        .all()
    )
    total_clip_count, daily_clip_counts = await _clip_stats(session, account.id)
    return BlinkStatusResponse(
        linked=True,
        status=account.status,
        last_sync=account.last_sync,
        last_error=account.last_error,
        camera_count=camera_count,
        network_ids=list(network_ids),
        total_clip_count=total_clip_count,
        daily_clip_counts=daily_clip_counts,
    )


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> dict[str, str]:
    if await _account_count(session) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No Blink account is linked."
        )
    await request.app.state.arq_redis.enqueue_job(SYNC_JOB_NAME)
    return {"status": "sync_started"}


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_account(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> None:
    account = (await session.execute(select(BlinkAccount))).scalars().first()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No Blink account is linked."
        )

    storage_root = await resolve_storage_dir(session, get_settings())
    storage = get_clip_storage(storage_root)
    clips = (
        (
            await session.execute(
                select(Clip).join(Camera).where(Camera.blink_account_id == account.id)
            )
        )
        .scalars()
        .all()
    )
    for clip in clips:
        try:
            # By the clip's own persisted paths, never a recompute - see
            # app.api.clips._delete_one's docstring for why.
            if clip.storage_path:
                await storage.delete(Path(clip.storage_path))
            thumb_path = clip.thumbnail_path or str(
                storage.legacy_thumbnail_path(clip.camera_id, clip.id)
            )
            await storage.delete(Path(thumb_path))
        except StorageError as exc:
            # Unlinking should never get stuck behind one bad file; the DB
            # row still goes away and the orphaned file can be cleaned up
            # manually — logged clearly so it isn't silently lost.
            logger.error("blink.unlink_file_cleanup_failed", clip_id=str(clip.id), error=str(exc))

    await session.delete(account)  # cascades to cameras, then clips
    await session.commit()
    logger.info("blink.account_unlinked", cameras=len({c.camera_id for c in clips}))
