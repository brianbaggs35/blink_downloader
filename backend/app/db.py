"""Async SQLAlchemy base, engine construction, and the request-scoped session."""

from collections.abc import AsyncIterator
from enum import StrEnum

from fastapi import Request
from sqlalchemy import Enum, MetaData
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
