"""get_or_create_singleton: the lazily-created fixed-id settings rows must
survive being created by several sessions at once."""

import asyncio
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import SINGLETON_ID as AI_SINGLETON_ID
from app.ai.models import AISettings
from app.alerts.models import SINGLETON_ID as ALERT_SINGLETON_ID
from app.alerts.models import AlertSettings
from app.biometrics.models import SINGLETON_ID as BIOMETRICS_SINGLETON_ID
from app.biometrics.models import BiometricsSettings
from app.db import Base, get_or_create_singleton
from app.integrations.models import SINGLETON_ID as INTEGRATIONS_SINGLETON_ID
from app.integrations.models import StorageIntegrationSettings
from app.livefeed.models import SINGLETON_ID as LIVEFEED_SINGLETON_ID
from app.livefeed.models import LiveViewSettings, SecurityFeedSettings
from app.settings.models import SINGLETON_ID as APP_SINGLETON_ID
from app.settings.models import AppSettings

SINGLETONS: list[tuple[type[Base], uuid.UUID]] = [
    (AppSettings, APP_SINGLETON_ID),
    (AISettings, AI_SINGLETON_ID),
    (AlertSettings, ALERT_SINGLETON_ID),
    (BiometricsSettings, BIOMETRICS_SINGLETON_ID),
    (LiveViewSettings, LIVEFEED_SINGLETON_ID),
    (SecurityFeedSettings, LIVEFEED_SINGLETON_ID),
    (StorageIntegrationSettings, INTEGRATIONS_SINGLETON_ID),
]
"""Every model the app reads through get_or_create_singleton."""


async def test_creates_then_reuses(app_session: AsyncSession) -> None:
    first = await get_or_create_singleton(app_session, AppSettings, APP_SINGLETON_ID)
    second = await get_or_create_singleton(app_session, AppSettings, APP_SINGLETON_ID)
    assert first is second
    assert first.id == APP_SINGLETON_ID


async def test_concurrent_first_reads_all_succeed(app_session: AsyncSession, app: FastAPI) -> None:
    """Ten sessions race to create the same row - the shape of the first
    bulk-analyze on a fresh install, where every worker job called
    get_biometrics_settings() in the same instant and all but one died on
    the primary key. Every caller must get the row; exactly one must exist."""
    del app_session  # only wanted for its TRUNCATE; the race needs separate sessions

    async def read_once() -> BiometricsSettings:
        async with app.state.sessionmaker() as session:
            row = await get_or_create_singleton(
                session, BiometricsSettings, BIOMETRICS_SINGLETON_ID
            )
            await session.commit()
            return row

    rows = await asyncio.gather(*(read_once() for _ in range(10)))
    assert {row.id for row in rows} == {BIOMETRICS_SINGLETON_ID}
    async with app.state.sessionmaker() as session:
        count = await session.scalar(select(func.count()).select_from(BiometricsSettings))
    assert count == 1


async def test_lost_race_recovers_inside_a_savepoint(
    app_session: AsyncSession, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forces the exact interleaving the SAVEPOINT exists for: the loser's
    read misses, a winner commits the row, then the loser's INSERT hits the
    primary key. The loser must get the winner's row back, and work it had
    already done in the same transaction must survive - without the
    SAVEPOINT the IntegrityError would abort the whole transaction."""
    loser = app_session
    # Pending, uncommitted work in the loser's transaction before the race.
    alert_settings = await get_or_create_singleton(loser, AlertSettings, ALERT_SINGLETON_ID)
    alert_settings.alert_on_low_battery = True

    async with app.state.sessionmaker() as winner:
        await get_or_create_singleton(winner, AISettings, AI_SINGLETON_ID)
        await winner.commit()

    real_get = loser.get
    reads: list[object] = []

    async def first_read_misses(model: type, ident: object, **kwargs: Any) -> object:
        # The loser read before the winner committed: its first look finds
        # nothing, so it goes on to INSERT. Later reads see the truth.
        result = (
            None if (model is AISettings and not reads) else await real_get(model, ident, **kwargs)
        )
        if model is AISettings:
            reads.append(result)
        return result

    monkeypatch.setattr(loser, "get", first_read_misses)
    row = await get_or_create_singleton(loser, AISettings, AI_SINGLETON_ID)

    assert row.id == AI_SINGLETON_ID
    # Took the IntegrityError path: the initial miss, then the recovering re-read.
    assert reads[0] is None and reads[1] is not None and len(reads) == 2
    # The outer transaction is intact: both its earlier pending change and a
    # new one commit together.
    row.enabled = True
    await loser.commit()
    async with app.state.sessionmaker() as check:
        assert (await check.get(AISettings, AI_SINGLETON_ID)).enabled is True  # pyright: ignore[reportOptionalMemberAccess]
        assert (await check.get(AlertSettings, ALERT_SINGLETON_ID)).alert_on_low_battery is True  # pyright: ignore[reportOptionalMemberAccess]


@pytest.mark.parametrize(
    ("model", "singleton_id"), SINGLETONS, ids=[model.__name__ for model, _ in SINGLETONS]
)
async def test_every_singleton_model_recovers_from_a_lost_race(
    app_session: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    model: type[Base],
    singleton_id: uuid.UUID,
) -> None:
    """The same forced interleaving, for each model the app reads this way:
    its first read misses, a winner commits the row, and its INSERT then
    hits the primary key. Proves the helper is generic, not tuned to one
    table's defaults or constraints."""
    loser = app_session
    async with app.state.sessionmaker() as winner:
        await get_or_create_singleton(winner, model, singleton_id)
        await winner.commit()

    real_get = loser.get
    missed: list[bool] = []

    async def first_read_misses(cls: type[Base], ident: object, **kwargs: Any) -> object:
        if cls is model and not missed:
            missed.append(True)
            return None
        return await real_get(cls, ident, **kwargs)

    monkeypatch.setattr(loser, "get", first_read_misses)
    row = await get_or_create_singleton(loser, model, singleton_id)

    assert missed == [True]  # it really did take the INSERT path
    assert inspect(row).identity == (singleton_id,)
    await loser.commit()
    async with app.state.sessionmaker() as check:
        assert await check.scalar(select(func.count()).select_from(model)) == 1


class _NotNullViolationError(Exception):
    sqlstate = "23502"


async def test_an_integrity_error_that_is_not_a_conflict_is_raised(
    app_session: AsyncSession, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a unique/primary-key conflict means "someone else created it".
    Arranged so that treating any other IntegrityError as a lost race would
    hide it: the row does exist to be re-read, but this INSERT failed for a
    different reason (a NOT NULL violation)."""
    async with app.state.sessionmaker() as other:
        await get_or_create_singleton(other, AppSettings, APP_SINGLETON_ID)
        await other.commit()

    real_get = app_session.get
    missed: list[bool] = []

    async def first_read_misses(cls: type[Base], ident: object, **kwargs: Any) -> object:
        if not missed:
            missed.append(True)
            return None
        return await real_get(cls, ident, **kwargs)

    async def flush_fails(*_args: object, **_kwargs: object) -> None:
        raise IntegrityError("INSERT INTO app_settings ...", {}, _NotNullViolationError())

    monkeypatch.setattr(app_session, "get", first_read_misses)
    monkeypatch.setattr(app_session, "flush", flush_fails)
    with pytest.raises(IntegrityError):
        await get_or_create_singleton(app_session, AppSettings, APP_SINGLETON_ID)
