"""ASGI middleware attaching security headers to every API response.

Browser-facing headers (HSTS, the SPA's CSP) live in the nginx layer; these
cover the API surface itself, including direct access in development.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

SECURITY_HEADERS: dict[bytes, bytes] = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"strict-origin-when-cross-origin",
    b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
    b"cross-origin-opener-policy": b"same-origin",
    b"cross-origin-resource-policy": b"same-origin",
    b"cache-control": b"no-store",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(SECURITY_HEADERS.items())
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
