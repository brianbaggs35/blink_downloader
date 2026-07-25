"""BlinkLinker: interactive account linking, including the 2FA hand-off.

Fakes stand in for blinkpy's ``Auth`` (patched at the name imported into
``app.blink.linker``) — no real network involved.
"""

# White-box: reaches into BlinkLinker's private pending-session dict, and
# FakeAuth structurally (not nominally) stands in for blinkpy's untyped Auth.
# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# blinkpy ships no type stubs (no py.typed marker).
# pyright: reportPrivateUsage=false
# pyright: reportArgumentType=false
# pyright: reportUnusedFunction=false
# pyright: reportMissingTypeStubs=false

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientConnectionError
from blinkpy.auth import BlinkTwoFARequiredError, LoginError

from app.blink.linker import (
    LINK_SESSION_TTL,
    BlinkConnectionError,
    BlinkInvalidCodeError,
    BlinkInvalidCredentialsError,
    BlinkLinker,
    BlinkLinkSessionExpiredError,
    _PendingLink,
)


class FakeSession:
    def __init__(self) -> None:
        self.close = AsyncMock()


class FakeAuth:
    """Class-level defaults so a test can override behavior before
    ``BlinkLinker`` constructs its own instance internally."""

    startup_error: ClassVar[Exception | None] = None
    complete_2fa_result: ClassVar[bool] = True
    complete_2fa_error: ClassVar[Exception | None] = None

    def __init__(self, login_data: dict[str, Any] | None = None, **_kwargs: Any) -> None:
        self.login_data = login_data or {}
        self.session = FakeSession()
        self.complete_2fa_calls: list[str] = []

    async def startup(self) -> None:
        if self.startup_error:
            raise self.startup_error

    async def complete_2fa_login(self, code: str) -> bool:
        self.complete_2fa_calls.append(code)
        if self.complete_2fa_error:
            raise self.complete_2fa_error
        return self.complete_2fa_result

    @property
    def login_attributes(self) -> dict[str, Any]:
        return {**self.login_data, "token": "final-token"}


@pytest.fixture(autouse=True)
def _patch_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.blink.linker.Auth", FakeAuth)
    monkeypatch.setattr(FakeAuth, "startup_error", None)
    monkeypatch.setattr(FakeAuth, "complete_2fa_result", True)
    monkeypatch.setattr(FakeAuth, "complete_2fa_error", None)


@pytest.fixture
def linker() -> BlinkLinker:
    return BlinkLinker()


async def test_start_link_success_returns_token_data(linker: BlinkLinker) -> None:
    outcome = await linker.start_link("brian@example.com", "hunter2")
    assert outcome.verification_required is False
    assert outcome.token_data == {
        "username": "brian@example.com",
        "password": "hunter2",
        "token": "final-token",
    }
    assert linker._pending == {}


async def test_start_link_requires_2fa(
    linker: BlinkLinker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeAuth, "startup_error", BlinkTwoFARequiredError())

    outcome = await linker.start_link("brian@example.com", "hunter2")

    assert outcome.verification_required is True
    assert outcome.link_session_id is not None
    assert len(linker._pending) == 1


async def test_start_link_rejects_bad_credentials(
    linker: BlinkLinker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeAuth, "startup_error", LoginError("nope"))

    with pytest.raises(BlinkInvalidCredentialsError):
        await linker.start_link("brian@example.com", "wrong")
    assert linker._pending == {}


async def test_start_link_maps_connection_errors(
    linker: BlinkLinker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeAuth, "startup_error", ClientConnectionError("dns failure"))

    with pytest.raises(BlinkConnectionError):
        await linker.start_link("brian@example.com", "hunter2")


async def test_complete_2fa_success(linker: BlinkLinker) -> None:
    auth = FakeAuth()
    session_id = uuid.uuid4()
    linker._pending[session_id] = _PendingLink(
        auth=auth, username="brian@example.com", password="hunter2"
    )

    token_data = await linker.complete_2fa(session_id, "123456")

    assert token_data == auth.login_attributes
    assert auth.complete_2fa_calls == ["123456"]
    auth.session.close.assert_awaited_once()
    assert session_id not in linker._pending


async def test_pending_credentials_returns_username_password(linker: BlinkLinker) -> None:
    session_id = uuid.uuid4()
    linker._pending[session_id] = _PendingLink(auth=FakeAuth(), username="u", password="p")
    assert linker.pending_credentials(session_id) == ("u", "p")


def test_pending_credentials_none_for_unknown_session(linker: BlinkLinker) -> None:
    assert linker.pending_credentials(uuid.uuid4()) is None


async def test_complete_2fa_unknown_session_raises_expired(linker: BlinkLinker) -> None:
    with pytest.raises(BlinkLinkSessionExpiredError):
        await linker.complete_2fa(uuid.uuid4(), "123456")


async def test_complete_2fa_wrong_code_keeps_session_for_retry(
    linker: BlinkLinker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeAuth, "complete_2fa_result", False)
    auth = FakeAuth()
    session_id = uuid.uuid4()
    linker._pending[session_id] = _PendingLink(auth=auth, username="u", password="p")

    with pytest.raises(BlinkInvalidCodeError):
        await linker.complete_2fa(session_id, "000000")

    assert session_id in linker._pending  # still there — the user can retry the code
    auth.session.close.assert_not_awaited()


async def test_complete_2fa_connection_error(
    linker: BlinkLinker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeAuth, "complete_2fa_error", ClientConnectionError("timeout"))
    auth = FakeAuth()
    session_id = uuid.uuid4()
    linker._pending[session_id] = _PendingLink(auth=auth, username="u", password="p")

    with pytest.raises(BlinkConnectionError):
        await linker.complete_2fa(session_id, "123456")
    assert session_id in linker._pending


async def test_expired_sessions_are_swept_and_closed(linker: BlinkLinker) -> None:
    auth = FakeAuth()
    session_id = uuid.uuid4()
    linker._pending[session_id] = _PendingLink(
        auth=auth,
        username="u",
        password="p",
        created_at=datetime.now(UTC) - LINK_SESSION_TTL - timedelta(seconds=1),
    )

    with pytest.raises(BlinkLinkSessionExpiredError):
        await linker.complete_2fa(session_id, "123456")

    auth.session.close.assert_awaited_once()
    assert linker._pending == {}


async def test_cancel_closes_and_removes_pending_session(linker: BlinkLinker) -> None:
    auth = FakeAuth()
    session_id = uuid.uuid4()
    linker._pending[session_id] = _PendingLink(auth=auth, username="u", password="p")

    await linker.cancel(session_id)

    auth.session.close.assert_awaited_once()
    assert session_id not in linker._pending


async def test_cancel_unknown_session_is_a_noop(linker: BlinkLinker) -> None:
    await linker.cancel(uuid.uuid4())  # must not raise


async def test_aclose_closes_every_pending_session(linker: BlinkLinker) -> None:
    auth_a, auth_b = FakeAuth(), FakeAuth()
    linker._pending[uuid.uuid4()] = _PendingLink(auth=auth_a, username="a", password="a")
    linker._pending[uuid.uuid4()] = _PendingLink(auth=auth_b, username="b", password="b")

    await linker.aclose()

    auth_a.session.close.assert_awaited_once()
    auth_b.session.close.assert_awaited_once()
    assert linker._pending == {}
