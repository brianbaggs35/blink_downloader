"""Blink account sync: refresh cameras, discover new clips, fan out downloads.

Self-reschedules at ``BLINK_SYNC_INTERVAL_SECONDS`` via a ``finally`` block —
arq's calendar-style cron (fixed second-of-minute) can't express an
arbitrary N-second interval, so this uses the standard arq idiom of a job
that re-enqueues itself on completion.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.blink.models import BlinkAccount, BlinkAccountStatus, Camera, Clip
from app.blink.service import (
    BlinkAuthError,
    BlinkCameraInfo,
    BlinkError,
    BlinkPyService,
    BlinkSyncModuleInfo,
)
from app.config import Settings, get_settings
from app.logs import get_logger
from app.security.crypto import SecretBox
from app.settings.service import (
    resolve_blink_auto_analyze_limit,
    resolve_blink_initial_sync_days,
    resolve_blink_sync_interval_seconds,
)
from app.sync_module.models import SyncModule
from app.worker.tasks.download import DOWNLOAD_JOB_NAME

logger = get_logger(__name__)

SYNC_JOB_NAME = "sync_blink_account"


async def sync_blink_account(ctx: dict[Any, Any]) -> str:
    settings = get_settings()
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    # Its own short-lived session: needed in the finally block below, by
    # which point _run_sync's own session has already closed.
    async with sessionmaker() as session:
        sync_interval_seconds = await resolve_blink_sync_interval_seconds(session, settings)
    try:
        async with sessionmaker() as session:
            return await _run_sync(session, settings, ctx)
    finally:
        # No _job_id pinning: an on-demand "sync now" trigger must be able to
        # enqueue even while a deferred run is already queued. _run_sync is
        # upsert-based throughout, so an occasional overlapping run is
        # harmless, just a little redundant work.
        await ctx["redis"].enqueue_job(SYNC_JOB_NAME, _defer_by=sync_interval_seconds)


async def _run_sync(session: AsyncSession, settings: Settings, ctx: dict[Any, Any]) -> str:
    account = (await session.execute(select(BlinkAccount))).scalars().first()
    if account is None:
        return "no_account_linked"

    box = SecretBox(settings.encryption_key)
    token_data = json.loads(box.decrypt(account.encrypted_token_data))
    service = BlinkPyService(token_data)
    try:
        cameras = await service.get_cameras()
        sync_modules = await service.get_sync_modules()
        since = account.last_sync or (
            datetime.now(UTC)
            - timedelta(days=await resolve_blink_initial_sync_days(session, settings))
        )
        media_items = await service.list_media(since=since)
    except BlinkAuthError as exc:
        account.status = BlinkAccountStatus.ERROR
        account.last_error = str(exc)
        await session.commit()
        logger.warning("blink.sync_auth_failed", account_id=str(account.id), error=str(exc))
        return "auth_error"
    except BlinkError as exc:
        account.status = BlinkAccountStatus.ERROR
        account.last_error = str(exc)
        await session.commit()
        logger.warning("blink.sync_failed", account_id=str(account.id), error=str(exc))
        return "error"
    finally:
        await service.close()

    cameras_by_name = await _upsert_cameras(session, account, cameras)
    await _upsert_sync_modules(session, account, sync_modules)
    new_clips = await _insert_new_clips(session, cameras_by_name, media_items)

    account.status = BlinkAccountStatus.ACTIVE
    account.last_error = None
    account.last_sync = datetime.now(UTC)
    account.encrypted_token_data = box.encrypt(json.dumps(service.token_data))
    await session.commit()

    auto_analyze_limit = await resolve_blink_auto_analyze_limit(session, settings)
    auto_analyze_ids = _select_auto_analyze_ids(new_clips, auto_analyze_limit)
    for clip_id, _recorded_at in new_clips:
        await ctx["redis"].enqueue_job(
            DOWNLOAD_JOB_NAME, clip_id=str(clip_id), auto_analyze=clip_id in auto_analyze_ids
        )

    logger.info(
        "blink.sync_completed",
        account_id=str(account.id),
        cameras=len(cameras),
        new_clips=len(new_clips),
        queued_for_analysis=len(auto_analyze_ids),
    )
    return "ok"


def _select_auto_analyze_ids(new_clips: list[tuple[UUID, datetime]], limit: int) -> set[UUID]:
    """The N most recently recorded clips from this sync, auto-queued for AI
    analysis. Caps a first-connection or post-outage backlog from flooding
    the analysis queue — everything still downloads, just not all of it gets
    auto-analyzed. See resolve_blink_auto_analyze_limit."""
    newest_first = sorted(new_clips, key=lambda pair: pair[1], reverse=True)
    return {clip_id for clip_id, _recorded_at in newest_first[:limit]}


async def _upsert_cameras(
    session: AsyncSession, account: BlinkAccount, cameras: list[BlinkCameraInfo]
) -> dict[str, Camera]:
    by_name: dict[str, Camera] = {}
    for info in cameras:
        stmt = (
            insert(Camera)
            .values(
                blink_account_id=account.id,
                blink_camera_id=info.camera_id,
                blink_network_id=info.network_id,
                name=info.name,
                camera_type=info.camera_type,
                battery=info.battery,
                thumbnail_path=info.thumbnail_path,
                motion_enabled=info.motion_enabled,
                motion_action_type=info.motion_action_type,
                last_synced_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                index_elements=[Camera.blink_account_id, Camera.blink_camera_id],
                set_={
                    "name": info.name,
                    "camera_type": info.camera_type,
                    "battery": info.battery,
                    "thumbnail_path": info.thumbnail_path,
                    "motion_enabled": info.motion_enabled,
                    "motion_action_type": info.motion_action_type,
                    "last_synced_at": datetime.now(UTC),
                },
            )
            .returning(Camera)
        )
        camera = (await session.execute(stmt)).scalar_one()
        by_name[info.name.lower()] = camera
    return by_name


async def _insert_new_clips(
    session: AsyncSession,
    cameras_by_name: dict[str, Camera],
    media_items: list[Any],
) -> list[tuple[UUID, datetime]]:
    new_clips: list[tuple[UUID, datetime]] = []
    for item in media_items:
        if item.deleted:
            continue
        camera = cameras_by_name.get(item.camera_name.lower())
        if camera is None:
            logger.warning("blink.sync_unknown_camera", camera_name=item.camera_name)
            continue

        stmt = (
            insert(Clip)
            .values(
                camera_id=camera.id,
                blink_clip_id=item.media_id,
                recorded_at=item.created_at,
                raw_metadata=item.raw,
            )
            .on_conflict_do_nothing(index_elements=[Clip.camera_id, Clip.blink_clip_id])
            .returning(Clip.id, Clip.recorded_at)
        )
        result = await session.execute(stmt)
        row = result.first()
        if row is not None:
            new_clips.append((row[0], row[1]))
    return new_clips


async def _upsert_sync_modules(
    session: AsyncSession, account: BlinkAccount, sync_modules: list[BlinkSyncModuleInfo]
) -> None:
    """Cheap identity/arm/online/local-storage-flags state, piggybacked on
    this same sync cycle - the expensive part (the local-storage manifest
    itself) is never folded in here, only ever refreshed on demand from the
    Sync Module tab (see app.worker.tasks.sync_module)."""
    for info in sync_modules:
        stmt = (
            insert(SyncModule)
            .values(
                blink_account_id=account.id,
                network_id=info.network_id,
                sync_id=info.sync_id,
                name=info.name,
                serial=info.serial,
                firmware_version=info.firmware_version,
                is_physical_hub=info.is_physical_hub,
                armed=info.armed,
                online=info.online,
                local_storage_compatible=info.local_storage_compatible,
                local_storage_enabled=info.local_storage_enabled,
                local_storage_active=info.local_storage_active,
                last_synced_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                index_elements=[SyncModule.blink_account_id, SyncModule.network_id],
                set_={
                    "sync_id": info.sync_id,
                    "name": info.name,
                    "serial": info.serial,
                    "firmware_version": info.firmware_version,
                    "is_physical_hub": info.is_physical_hub,
                    "armed": info.armed,
                    "online": info.online,
                    "local_storage_compatible": info.local_storage_compatible,
                    "local_storage_enabled": info.local_storage_enabled,
                    "local_storage_active": info.local_storage_active,
                    "last_synced_at": datetime.now(UTC),
                },
            )
            # RETURNING so a row already loaded in this session's identity
            # map (e.g. by a caller that queried it earlier) gets refreshed
            # with the new values - see _upsert_cameras above for the same
            # pattern, and app.sync_module.service's _reconcile_local_items
            # docstring for why this app's sessions need it explicitly.
            .returning(SyncModule)
        )
        (await session.execute(stmt)).scalar_one()
