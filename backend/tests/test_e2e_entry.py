"""The e2e container entrypoint migrates, seeds, then execs uvicorn."""

import asyncio
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db import build_engine, build_sessionmaker
from app.settings.service import set_storage_dir
from app.testing import e2e_entry
from app.testing.seed import E2E_ADMIN_EMAIL, E2E_VIEWER_EMAIL, wipe_all


async def _fresh_install(storage_dir: Path | None) -> None:
    """What the e2e container boots into: no accounts, no domain data, clips
    stored under ``storage_dir``. With None, this is the cleanup."""
    engine = build_engine(get_settings().database_url)
    try:
        sessionmaker = build_sessionmaker(engine)
        async with sessionmaker() as session:
            await wipe_all(session)
            await set_storage_dir(session, None if storage_dir is None else str(storage_dir))
    finally:
        await engine.dispose()


async def _user_emails() -> set[str]:
    engine = build_engine(get_settings().database_url)
    try:
        sessionmaker = build_sessionmaker(engine)
        async with sessionmaker() as session:
            return set((await session.execute(text("SELECT email FROM users"))).scalars())
    finally:
        await engine.dispose()


def test_main_migrates_seeds_and_execs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Start from a fresh install rather than whatever the previous test left.
    # Inheriting it made this pass or fail by test order: with one user
    # already present the seed skipped itself entirely (and the count of one
    # was that user), and with none it wrote clips under the /data default,
    # which a CI runner can't.
    asyncio.run(_fresh_install(tmp_path))
    captured: dict[str, object] = {}

    def fake_execv(path: str, argv: list[str]) -> None:
        captured["path"] = path
        captured["argv"] = argv

    monkeypatch.setattr(e2e_entry.os, "execv", fake_execv)
    try:
        e2e_entry.main()

        assert captured["path"] == sys.executable
        argv = captured["argv"]
        assert isinstance(argv, list)
        assert "app.main:app" in argv
        assert "--proxy-headers" in argv

        assert asyncio.run(_user_emails()) == {E2E_ADMIN_EMAIL, E2E_VIEWER_EMAIL}
        assert any(path.is_file() for path in tmp_path.rglob("*"))  # the data seed ran too
    finally:
        asyncio.run(_fresh_install(None))
