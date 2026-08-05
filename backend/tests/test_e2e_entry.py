"""The e2e container entrypoint migrates, seeds, then execs uvicorn."""

import asyncio
import sys

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db import build_engine, build_sessionmaker
from app.testing import e2e_entry


async def _seeded_user_count_and_cleanup() -> int:
    engine = build_engine(get_settings().database_url)
    try:
        sessionmaker = build_sessionmaker(engine)
        async with sessionmaker() as session:
            count = (await session.execute(text("SELECT COUNT(*) FROM users"))).scalar_one()
            await session.execute(text("TRUNCATE TABLE access_tokens, users CASCADE"))
            await session.commit()
            return int(count)
    finally:
        await engine.dispose()


def test_main_migrates_seeds_and_execs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_execv(path: str, argv: list[str]) -> None:
        captured["path"] = path
        captured["argv"] = argv

    monkeypatch.setattr(e2e_entry.os, "execv", fake_execv)
    e2e_entry.main()

    assert captured["path"] == sys.executable
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert "app.main:app" in argv
    assert "--proxy-headers" in argv

    assert asyncio.run(_seeded_user_count_and_cleanup()) == 1
