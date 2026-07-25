"""python -m app.cli create-admin: the escape hatch alongside /api/setup."""

import sys

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import create_admin, main, prompt_credentials
from app.users.models import User

# fastapi_users_db_sqlalchemy's User.email stub doesn't signal that it's a
# comparable InstrumentedAttribute the way our own models' columns do (see
# the identical reportIncompatibleVariableOverride workaround in
# app/users/models.py) - the equality comparison itself is the normal,
# correct SQLAlchemy pattern (already used elsewhere, e.g. test_api_clips.py).


async def test_create_admin_creates_a_new_account(app_session: AsyncSession) -> None:
    await create_admin("new-admin@example.com", "a-fine-long-password", "New Admin")
    user = (
        await app_session.execute(
            select(User).where(User.email == "new-admin@example.com")  # pyright: ignore[reportArgumentType]
        )
    ).scalar_one()
    assert user.is_superuser is True
    assert user.is_verified is True
    assert user.display_name == "New Admin"
    assert user.hashed_password.startswith("$argon2id$")


async def test_create_admin_promotes_and_resets_an_existing_account(
    app_session: AsyncSession,
) -> None:
    await create_admin("person@example.com", "the-first-password-here", "Person")
    await create_admin("person@example.com", "a-totally-different-password", "Person")

    users = (
        (
            await app_session.execute(
                select(User).where(User.email == "person@example.com")  # pyright: ignore[reportArgumentType]
            )
        )
        .scalars()
        .all()
    )
    assert len(users) == 1
    assert users[0].is_superuser is True


async def test_create_admin_rejects_a_weak_password(
    app_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        await create_admin("weak@example.com", "short", "Weak")
    assert "Password rejected" in capsys.readouterr().err

    count = (await app_session.execute(select(User))).scalars().all()
    assert count == []


async def test_create_admin_rejects_a_weak_password_on_the_update_path(
    app_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    await create_admin("person2@example.com", "a-fine-long-password", "Person")
    with pytest.raises(SystemExit):
        await create_admin("person2@example.com", "short", "Person")
    assert "Password rejected" in capsys.readouterr().err


def test_prompt_credentials_returns_provided_values_without_prompting() -> None:
    email, password = prompt_credentials("given@example.com", "given-password")
    assert (email, password) == ("given@example.com", "given-password")


def test_prompt_credentials_prompts_for_missing_email(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_input(_prompt: str) -> str:
        return "typed@example.com"

    monkeypatch.setattr("builtins.input", fake_input)
    email, password = prompt_credentials(None, "given-password")
    assert email == "typed@example.com"
    assert password == "given-password"


def test_prompt_credentials_prompts_for_missing_password(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["typed-password", "typed-password"])

    def fake_getpass(_prompt: str) -> str:
        return next(answers)

    monkeypatch.setattr("app.cli.getpass.getpass", fake_getpass)
    email, password = prompt_credentials("given@example.com", None)
    assert email == "given@example.com"
    assert password == "typed-password"


def test_prompt_credentials_exits_on_password_mismatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = iter(["one-password", "a-different-password"])

    def fake_getpass(_prompt: str) -> str:
        return next(answers)

    monkeypatch.setattr("app.cli.getpass.getpass", fake_getpass)
    with pytest.raises(SystemExit):
        prompt_credentials("given@example.com", None)
    assert "did not match" in capsys.readouterr().err


def test_main_wires_flags_through_to_create_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app.cli",
            "create-admin",
            "--email",
            "cli-main@example.com",
            "--password",
            "a-fine-long-password",
            "--display-name",
            "CLI Main",
        ],
    )
    called: dict[str, tuple[str, str, str]] = {}

    async def fake_create_admin(email: str, password: str, display_name: str) -> None:
        called["args"] = (email, password, display_name)

    monkeypatch.setattr("app.cli.create_admin", fake_create_admin)
    main()
    assert called["args"] == ("cli-main@example.com", "a-fine-long-password", "CLI Main")
