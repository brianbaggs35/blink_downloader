"""Async SQLAlchemy base, engine construction, and the request-scoped session."""

import uuid
from collections.abc import AsyncIterator
from enum import StrEnum

from fastapi import Request
from sqlalchemy import Enum, MetaData
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def build_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


def str_enum(enum_cls: type[StrEnum], name: str, *, length: int | None = None) -> Enum:
    """A VARCHAR + CHECK constraint rather than a Postgres enum type, so
    adding a value later is a plain migration, not a multi-step ALTER TYPE
    dance. Length defaults to the longest member's value, with room to
    override for a table whose column width is already fixed."""
    resolved_length = length or max(len(member.value) for member in enum_cls)
    return Enum(
        enum_cls, name=name, native_enum=False, length=resolved_length, validate_strings=True
    )


UNIQUE_VIOLATION = "23505"
"""Postgres's SQLSTATE for a unique or primary-key conflict - the only
IntegrityError a lost race can raise. Any other (a NOT NULL or CHECK
violation from a model default, say) is a real bug, not a race, and must
not be retried as one."""


async def get_or_create_singleton[Row: Base](
    session: AsyncSession, model: type[Row], singleton_id: uuid.UUID
) -> Row:
    """The fixed-id settings rows (app/ai/alert/biometrics/...) are created
    lazily on first read. Two sessions can both find the row missing and both
    try to insert it - the second INSERT then dies on the primary key - and
    that isn't a theoretical race: the first bulk-analyze on a fresh install
    starts up to ten worker jobs in the same instant, and all but one failed
    exactly this way (an unhandled IntegrityError, which arq does not retry).

    The insert runs inside a SAVEPOINT so a lost race rolls back just that
    statement, not the caller's whole transaction; Postgres has already made
    the winner's row visible by then (the losing INSERT blocks until the
    conflicting transaction commits), so re-reading it always succeeds."""
    row = await session.get(model, singleton_id)
    if row is not None:
        return row
    try:
        async with session.begin_nested():
            row = model(id=singleton_id)
            session.add(row)
            await session.flush()
    except IntegrityError as exc:
        # asyncpg and psycopg both expose the SQLSTATE as .sqlstate.
        if getattr(exc.orig, "sqlstate", None) != UNIQUE_VIOLATION:
            raise
        row = await session.get(model, singleton_id)
        if row is None:  # pragma: no cover - the conflicting row must exist to have conflicted
            raise
    return row
