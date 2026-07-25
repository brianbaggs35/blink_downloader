"""Every API response carries the security headers."""

from httpx import AsyncClient

from app.security.headers import SECURITY_HEADERS


async def test_security_headers_present(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name.decode()] == value.decode()


async def test_headers_present_on_errors_too(client: AsyncClient) -> None:
    response = await client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
