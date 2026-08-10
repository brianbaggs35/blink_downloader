"""GET/PUT /api/livefeed/settings/live-view and /security-feed."""

from uuid import uuid4

from httpx import AsyncClient


async def test_live_view_get_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/livefeed/settings/live-view")
    assert response.status_code == 401


async def test_live_view_get_defaults(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/livefeed/settings/live-view")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "default_camera_id": None,
        "auto_refresh_enabled": False,
        "auto_refresh_interval_seconds": 10,
    }


async def test_live_view_get_available_to_a_viewer(viewer_client: AsyncClient) -> None:
    response = await viewer_client.get("/api/livefeed/settings/live-view")
    assert response.status_code == 200


async def test_live_view_put_requires_superuser(viewer_client: AsyncClient) -> None:
    response = await viewer_client.put(
        "/api/livefeed/settings/live-view",
        json={
            "default_camera_id": None,
            "auto_refresh_enabled": True,
            "auto_refresh_interval_seconds": 15,
        },
    )
    assert response.status_code == 403


async def test_live_view_put_updates_and_persists(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/livefeed/settings/live-view",
        json={
            "default_camera_id": None,
            "auto_refresh_enabled": True,
            "auto_refresh_interval_seconds": 15,
        },
    )
    assert response.status_code == 200
    assert response.json()["auto_refresh_enabled"] is True

    followup = await admin_client.get("/api/livefeed/settings/live-view")
    assert followup.json()["auto_refresh_interval_seconds"] == 15


async def test_live_view_put_rejects_an_out_of_range_interval(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/livefeed/settings/live-view",
        json={
            "default_camera_id": None,
            "auto_refresh_enabled": True,
            "auto_refresh_interval_seconds": 1,
        },
    )
    assert response.status_code == 422


async def test_security_feed_get_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/livefeed/settings/security-feed")
    assert response.status_code == 401


async def test_security_feed_get_defaults(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/livefeed/settings/security-feed")
    assert response.status_code == 200
    assert response.json() == {
        "camera_ids": [],
        "columns": 2,
        "refresh_interval_seconds": 20,
        "refresh_mode": "interval",
    }


async def test_security_feed_put_requires_superuser(viewer_client: AsyncClient) -> None:
    response = await viewer_client.put(
        "/api/livefeed/settings/security-feed",
        json={"camera_ids": [], "columns": 3, "refresh_interval_seconds": 30},
    )
    assert response.status_code == 403


async def test_security_feed_put_updates_and_persists(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/livefeed/settings/security-feed",
        json={"camera_ids": [], "columns": 3, "refresh_interval_seconds": 30},
    )
    assert response.status_code == 200
    assert response.json()["columns"] == 3

    followup = await admin_client.get("/api/livefeed/settings/security-feed")
    assert followup.json()["refresh_interval_seconds"] == 30


async def test_security_feed_put_defaults_refresh_mode_to_interval(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.put(
        "/api/livefeed/settings/security-feed",
        json={"camera_ids": [], "columns": 2, "refresh_interval_seconds": 20},
    )
    assert response.json()["refresh_mode"] == "interval"


async def test_security_feed_put_sets_motion_mode_and_persists(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/livefeed/settings/security-feed",
        json={
            "camera_ids": [],
            "columns": 2,
            "refresh_interval_seconds": 20,
            "refresh_mode": "motion",
        },
    )
    assert response.status_code == 200
    assert response.json()["refresh_mode"] == "motion"

    followup = await admin_client.get("/api/livefeed/settings/security-feed")
    assert followup.json()["refresh_mode"] == "motion"


async def test_security_feed_put_rejects_too_many_cameras(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/livefeed/settings/security-feed",
        json={
            "camera_ids": [str(uuid4()) for _ in range(25)],
            "columns": 2,
            "refresh_interval_seconds": 20,
        },
    )
    assert response.status_code == 422


async def test_security_feed_put_rejects_out_of_range_columns(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/livefeed/settings/security-feed",
        json={"camera_ids": [], "columns": 9, "refresh_interval_seconds": 20},
    )
    assert response.status_code == 422
