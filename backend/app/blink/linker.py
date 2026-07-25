"""Interactive account linking: username/password, optionally followed by 2FA.

blinkpy's OAuth2+PKCE flow holds transient state (a CSRF token and a PKCE code
verifier) as plain attributes on the live ``Auth`` instance between "submit
credentials" and "submit the 2FA code" — there is nothing to serialize across
that gap. So a pending link keeps that ``Auth`` object alive in memory,
keyed by a short-lived session id, until the code arrives or the window
expires.
"""

# blinkpy ships no type stubs (no py.typed marker); every value that
# round-trips through it comes back Unknown to the type checker.
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from aiohttp import ClientError
from blinkpy.auth import Auth, BlinkTwoFARequiredError, LoginError, UnauthorizedError

from app.blink.service import BlinkError
from app.logs import get_logger

logger = get_logger(__name__)

LINK_SESSION_TTL = timedelta(minutes=10)


class BlinkConnectionError(BlinkError):
    """Blink's servers could not be reached (network/timeout), not a bad login."""


class BlinkInvalidCredentialsError(BlinkError):
    """Blink rejected the username/password."""


class BlinkInvalidCodeError(BlinkError):
    """Blink rejected the 2FA code. The link session is still usable to retry."""


class BlinkLinkSessionExpiredError(BlinkError):
    """No pending link with this id, or it expired. Start over."""


@dataclass
class LinkOutcome:
    verification_required: bool
    link_session_id: uuid.UUID | None = None
    token_data: dict[str, object] | None = None


@dataclass
class _PendingLink:
    auth: Auth
    username: str
    password: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) - self.created_at > LINK_SESSION_TTL


class BlinkLinker:
    """Owned by ``app.state`` — one per running API process."""

    def __init__(self) -> None:
        self._pending: dict[uuid.UUID, _PendingLink] = {}

    async def _sweep_expired(self) -> None:
        expired = [sid for sid, link in self._pending.items() if link.expired]
        for session_id in expired:
            link = self._pending.pop(session_id)
            await link.auth.session.close()
            logger.info("blink.link_session_expired", session_id=str(session_id))

    async def start_link(self, username: str, password: str) -> LinkOutcome:
        await self._sweep_expired()
        auth = Auth(login_data={"username": username, "password": password}, no_prompt=True)
        try:
            await auth.startup()
        except BlinkTwoFARequiredError:
            session_id = uuid.uuid4()
            self._pending[session_id] = _PendingLink(
                auth=auth, username=username, password=password
            )
            logger.info("blink.link_2fa_required", session_id=str(session_id))
            return LinkOutcome(verification_required=True, link_session_id=session_id)
        except (LoginError, UnauthorizedError) as exc:
            await auth.session.close()
            logger.info("blink.link_rejected", reason=str(exc))
            raise BlinkInvalidCredentialsError("Blink rejected that username or password.") from exc
        except (ClientError, TimeoutError) as exc:
            await auth.session.close()
            logger.warning("blink.link_connection_error", error=str(exc))
            raise BlinkConnectionError(
                "Could not reach Blink's servers. Try again shortly."
            ) from exc
        else:
            token_data = dict(auth.login_attributes)
            await auth.session.close()
            logger.info("blink.link_succeeded")
            return LinkOutcome(verification_required=False, token_data=token_data)

    async def complete_2fa(self, link_session_id: uuid.UUID, code: str) -> dict[str, object]:
        await self._sweep_expired()
        pending = self._pending.get(link_session_id)
        if pending is None:
            raise BlinkLinkSessionExpiredError(
                "This verification session has expired. Start the link again."
            )

        try:
            verified = await pending.auth.complete_2fa_login(code)
        except (ClientError, TimeoutError) as exc:
            logger.warning("blink.2fa_connection_error", error=str(exc))
            raise BlinkConnectionError(
                "Could not reach Blink's servers. Try again shortly."
            ) from exc

        if not verified:
            logger.info("blink.2fa_rejected", session_id=str(link_session_id))
            raise BlinkInvalidCodeError("That verification code was not accepted.")

        token_data = dict(pending.auth.login_attributes)
        await pending.auth.session.close()
        del self._pending[link_session_id]
        logger.info("blink.link_succeeded", via="2fa")
        return token_data

    def pending_credentials(self, link_session_id: uuid.UUID) -> tuple[str, str] | None:
        pending = self._pending.get(link_session_id)
        if pending is None:
            return None
        return pending.username, pending.password

    async def cancel(self, link_session_id: uuid.UUID) -> None:
        pending = self._pending.pop(link_session_id, None)
        if pending is not None:
            await pending.auth.session.close()

    async def aclose(self) -> None:
        for pending in self._pending.values():
            await pending.auth.session.close()
        self._pending.clear()
