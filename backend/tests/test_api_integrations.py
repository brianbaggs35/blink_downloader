"""/api/settings/storage-integrations/*: admin-only settings CRUD, a
combined test-connection endpoint, and the Google Drive/OneDrive OAuth
connect flows.

Everything below app.api.integrations's own imported names is faked -
google_drive_authorize_url/exchange_code, onedrive_authorize_url/
exchange_code, and the three build_*_client functions - so no real SDK
or network call ever happens (matching test_api_alerts.py's convention
of mocking at the names imported into the API module itself).
"""

# Untyped monkeypatch.setattr(str, lambda) call sites below - same as
# test_integrations_cloud.py.
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownLambdaType=false

from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient

from app.integrations.cloud import CloudStorageError


def _query(location: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(location).query)


async def test_get_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/settings/storage-integrations")).status_code == 401


async def test_get_requires_admin(viewer_client: AsyncClient) -> None:
    assert (await viewer_client.get("/api/settings/storage-integrations")).status_code == 403


async def test_get_defaults(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/settings/storage-integrations")
    assert response.status_code == 200
    body = response.json()
    assert body["s3_enabled"] is False
    assert body["s3_credentials_set"] is False
    assert body["google_drive_connected"] is False
    assert body["onedrive_connected"] is False
    assert body["auto_archive_backend"] == "local"


async def test_put_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.put("/api/settings/storage-integrations", json={})
    assert response.status_code == 403


async def test_put_sets_the_auto_archive_backend(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/settings/storage-integrations", json={"auto_archive_backend": "onedrive"}
    )
    assert response.status_code == 200
    assert response.json()["auto_archive_backend"] == "onedrive"


async def test_put_updates_and_never_echoes_secrets(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/settings/storage-integrations",
        json={
            "s3_enabled": True,
            "s3_bucket": "my-bucket",
            "s3_region": "us-east-1",
            "s3_access_key_id": "AKIA-super-secret-id",
            "s3_secret_access_key": "super-secret-key",
            "google_drive_enabled": True,
            "google_drive_client_id": "gd-client",
            "google_drive_client_secret": "gd-super-secret",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["s3_enabled"] is True
    assert body["s3_bucket"] == "my-bucket"
    assert body["s3_credentials_set"] is True
    assert body["google_drive_client_secret_set"] is True
    assert "super-secret" not in response.text
    assert "gd-super-secret" not in response.text


# --------------------------------------------------------------------- test


async def test_test_endpoint_requires_admin(viewer_client: AsyncClient) -> None:
    assert (await viewer_client.post("/api/settings/storage-integrations/test")).status_code == 403


async def test_test_endpoint_with_nothing_configured(admin_client: AsyncClient) -> None:
    response = await admin_client.post("/api/settings/storage-integrations/test")
    assert response.status_code == 200
    assert response.json() == {"s3": None, "google_drive": None, "onedrive": None}


async def test_test_endpoint_reports_per_provider_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    class _OkClient:
        async def test_connection(self) -> None:
            pass

    class _FailingClient:
        async def test_connection(self) -> None:
            raise CloudStorageError("bucket unreachable")

    monkeypatch.setattr("app.api.integrations.build_s3_client", lambda *_a, **_kw: _OkClient())
    monkeypatch.setattr(
        "app.api.integrations.build_google_drive_client", lambda *_a, **_kw: _FailingClient()
    )
    monkeypatch.setattr(
        "app.api.integrations.build_onedrive_client", lambda *_a, **_kw: _OkClient()
    )

    response = await admin_client.post("/api/settings/storage-integrations/test")
    assert response.status_code == 200
    body = response.json()
    assert body["s3"] == {"ok": True, "detail": "Connected."}
    assert body["google_drive"]["ok"] is False
    assert "bucket unreachable" in body["google_drive"]["detail"]
    assert body["onedrive"] == {"ok": True, "detail": "Connected."}


# ------------------------------------------------------------------- browse


class _FakeCloudClient:
    def __init__(
        self,
        folders: list[tuple[str, str]] | None = None,
        *,
        created_id: str = "new-1",
        raise_on_list: bool = False,
        raise_on_create: bool = False,
    ) -> None:
        self.folders = folders or []
        self.created_id = created_id
        self.raise_on_list = raise_on_list
        self.raise_on_create = raise_on_create
        self.list_calls: list[str | None] = []
        self.create_calls: list[tuple[str | None, str]] = []

    async def list_folders(self, parent: str | None = None) -> list[tuple[str, str]]:
        self.list_calls.append(parent)
        if self.raise_on_list:
            raise CloudStorageError("could not list folders")
        return self.folders

    async def create_folder(self, parent: str | None, name: str) -> str:
        self.create_calls.append((parent, name))
        if self.raise_on_create:
            raise CloudStorageError("could not create folder")
        return self.created_id


async def test_browse_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.get("/api/settings/storage-integrations/google_drive/browse")
    assert response.status_code == 403


async def test_browse_rejects_an_unrecognized_provider(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/settings/storage-integrations/dropbox/browse")
    assert response.status_code == 422


async def test_browse_when_the_provider_is_not_connected(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/settings/storage-integrations/onedrive/browse")
    assert response.status_code == 400
    assert "isn't connected yet" in response.json()["detail"]


async def test_browse_google_drive_lists_folders_at_the_root(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    fake = _FakeCloudClient([("f1", "Clips"), ("f2", "Backups")])
    monkeypatch.setattr("app.api.integrations.build_google_drive_client", lambda *_a, **_kw: fake)
    response = await admin_client.get("/api/settings/storage-integrations/google_drive/browse")
    assert response.status_code == 200
    assert response.json()["folders"] == [
        {"id": "f1", "name": "Clips"},
        {"id": "f2", "name": "Backups"},
    ]
    assert fake.list_calls == [None]


async def test_browse_onedrive_lists_folders_under_a_parent(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    fake = _FakeCloudClient([("f3", "2026")])
    monkeypatch.setattr("app.api.integrations.build_onedrive_client", lambda *_a, **_kw: fake)
    response = await admin_client.get(
        "/api/settings/storage-integrations/onedrive/browse", params={"parent": "f1"}
    )
    assert response.status_code == 200
    assert response.json()["folders"] == [{"id": "f3", "name": "2026"}]
    assert fake.list_calls == ["f1"]


async def test_browse_wraps_provider_errors(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    fake = _FakeCloudClient(raise_on_list=True)
    monkeypatch.setattr("app.api.integrations.build_s3_client", lambda *_a, **_kw: fake)
    response = await admin_client.get("/api/settings/storage-integrations/s3/browse")
    assert response.status_code == 400
    assert "could not list folders" in response.json()["detail"]


async def test_create_folder_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.post(
        "/api/settings/storage-integrations/google_drive/browse", json={"name": "New"}
    )
    assert response.status_code == 403


async def test_create_folder_when_the_provider_is_not_connected(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/settings/storage-integrations/onedrive/browse", json={"name": "New"}
    )
    assert response.status_code == 400
    assert "isn't connected yet" in response.json()["detail"]


async def test_create_folder_google_drive_at_the_root(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    fake = _FakeCloudClient([("new-1", "New Folder")], created_id="new-1")
    monkeypatch.setattr("app.api.integrations.build_google_drive_client", lambda *_a, **_kw: fake)
    response = await admin_client.post(
        "/api/settings/storage-integrations/google_drive/browse", json={"name": "New Folder"}
    )
    assert response.status_code == 201
    assert response.json()["folders"] == [{"id": "new-1", "name": "New Folder"}]
    assert fake.create_calls == [(None, "New Folder")]
    assert fake.list_calls == [None]


async def test_create_folder_onedrive_under_a_parent(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    fake = _FakeCloudClient([])
    monkeypatch.setattr("app.api.integrations.build_onedrive_client", lambda *_a, **_kw: fake)
    response = await admin_client.post(
        "/api/settings/storage-integrations/onedrive/browse",
        json={"parent_id": "f1", "name": "Subfolder"},
    )
    assert response.status_code == 201
    assert fake.create_calls == [("f1", "Subfolder")]
    assert fake.list_calls == ["f1"]


async def test_create_folder_wraps_provider_errors(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    fake = _FakeCloudClient(raise_on_create=True)
    monkeypatch.setattr("app.api.integrations.build_onedrive_client", lambda *_a, **_kw: fake)
    response = await admin_client.post(
        "/api/settings/storage-integrations/onedrive/browse", json={"name": "New"}
    )
    assert response.status_code == 400
    assert "could not create folder" in response.json()["detail"]


async def test_create_folder_rejects_a_blank_name(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/settings/storage-integrations/onedrive/browse", json={"name": ""}
    )
    assert response.status_code == 422


async def test_create_folder_s3_joins_the_parent_prefix_and_name(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    from app.integrations import cloud as cloud_module

    class _FakeS3(cloud_module.S3Client):
        def __init__(self) -> None:
            self.create_calls: list[str] = []
            self.list_calls: list[str | None] = []

        async def create_folder(self, prefix: str) -> str:  # type: ignore[override]
            self.create_calls.append(prefix)
            return prefix

        async def list_folders(  # type: ignore[override]
            self, prefix: str | None = None
        ) -> list[tuple[str, str]]:
            self.list_calls.append(prefix)
            return [(prefix or "", "New")]

    fake = _FakeS3()
    monkeypatch.setattr("app.api.integrations.build_s3_client", lambda *_a, **_kw: fake)
    response = await admin_client.post(
        "/api/settings/storage-integrations/s3/browse",
        json={"parent_id": "clips/2026", "name": "New"},
    )
    assert response.status_code == 201
    assert fake.create_calls == ["clips/2026/New"]


async def test_create_folder_s3_at_the_bucket_root(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    from app.integrations import cloud as cloud_module

    class _FakeS3(cloud_module.S3Client):
        def __init__(self) -> None:
            self.create_calls: list[str] = []

        async def create_folder(self, prefix: str) -> str:  # type: ignore[override]
            self.create_calls.append(prefix)
            return prefix

        async def list_folders(  # type: ignore[override]
            self, prefix: str | None = None
        ) -> list[tuple[str, str]]:
            return []

    fake = _FakeS3()
    monkeypatch.setattr("app.api.integrations.build_s3_client", lambda *_a, **_kw: fake)
    response = await admin_client.post(
        "/api/settings/storage-integrations/s3/browse", json={"name": "New"}
    )
    assert response.status_code == 201
    assert fake.create_calls == ["New"]


# ------------------------------------------------------------ google drive


async def test_google_drive_oauth_start_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.get(
        "/api/settings/storage-integrations/google-drive/oauth/start"
    )
    assert response.status_code == 403


async def test_google_drive_oauth_start_requires_saved_credentials(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.get(
        "/api/settings/storage-integrations/google-drive/oauth/start", follow_redirects=False
    )
    assert response.status_code == 400


async def test_google_drive_oauth_start_redirects_to_the_authorize_url(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    await admin_client.put(
        "/api/settings/storage-integrations",
        json={"google_drive_client_id": "gd-client", "google_drive_client_secret": "gd-secret"},
    )
    monkeypatch.setattr(
        "app.api.integrations.google_drive_authorize_url",
        lambda client_id, _client_secret, _redirect_uri, state: (
            f"https://accounts.google.com/authorize?client_id={client_id}&state={state}"
        ),
    )
    response = await admin_client.get(
        "/api/settings/storage-integrations/google-drive/oauth/start", follow_redirects=False
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/authorize")
    assert _query(location)["client_id"] == ["gd-client"]


async def test_google_drive_oauth_callback_rejects_a_missing_code(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.get(
        "/api/settings/storage-integrations/google-drive/oauth/callback", follow_redirects=False
    )
    assert response.headers["location"] == "/integrations?error=google_drive"


async def test_google_drive_oauth_callback_rejects_an_unknown_state(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.get(
        "/api/settings/storage-integrations/google-drive/oauth/callback",
        params={"code": "auth-code", "state": "not-the-real-state"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/integrations?error=google_drive"


async def test_google_drive_oauth_callback_rejects_credentials_cleared_after_start(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    await admin_client.put(
        "/api/settings/storage-integrations",
        json={"google_drive_client_id": "gd-client", "google_drive_client_secret": "gd-secret"},
    )
    monkeypatch.setattr(
        "app.api.integrations.google_drive_authorize_url",
        lambda _client_id, _client_secret, _redirect_uri, state: (
            f"https://accounts.google.com/?state={state}"
        ),
    )
    start_response = await admin_client.get(
        "/api/settings/storage-integrations/google-drive/oauth/start", follow_redirects=False
    )
    state = _query(start_response.headers["location"])["state"][0]

    await admin_client.put(
        "/api/settings/storage-integrations", json={"google_drive_client_id": None}
    )
    response = await admin_client.get(
        "/api/settings/storage-integrations/google-drive/oauth/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/integrations?error=google_drive"


async def test_google_drive_oauth_callback_completes_the_flow(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    await admin_client.put(
        "/api/settings/storage-integrations",
        json={"google_drive_client_id": "gd-client", "google_drive_client_secret": "gd-secret"},
    )
    monkeypatch.setattr(
        "app.api.integrations.google_drive_authorize_url",
        lambda _client_id, _client_secret, _redirect_uri, state: (
            f"https://accounts.google.com/?state={state}"
        ),
    )
    start_response = await admin_client.get(
        "/api/settings/storage-integrations/google-drive/oauth/start", follow_redirects=False
    )
    state = _query(start_response.headers["location"])["state"][0]

    async def _fake_exchange(
        _client_id: str, _client_secret: str, _redirect_uri: str, code: str
    ) -> str:
        assert code == "auth-code"
        return "gd-refresh-token"

    monkeypatch.setattr("app.api.integrations.google_drive_exchange_code", _fake_exchange)

    callback_response = await admin_client.get(
        "/api/settings/storage-integrations/google-drive/oauth/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    expected = "/integrations?connected=google_drive"
    assert callback_response.headers["location"] == expected

    settings_response = await admin_client.get("/api/settings/storage-integrations")
    assert settings_response.json()["google_drive_connected"] is True


async def test_google_drive_oauth_callback_wraps_exchange_errors(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    await admin_client.put(
        "/api/settings/storage-integrations",
        json={"google_drive_client_id": "gd-client", "google_drive_client_secret": "gd-secret"},
    )
    monkeypatch.setattr(
        "app.api.integrations.google_drive_authorize_url",
        lambda _client_id, _client_secret, _redirect_uri, state: (
            f"https://accounts.google.com/?state={state}"
        ),
    )
    start_response = await admin_client.get(
        "/api/settings/storage-integrations/google-drive/oauth/start", follow_redirects=False
    )
    state = _query(start_response.headers["location"])["state"][0]

    async def _raise(client_id: str, client_secret: str, redirect_uri: str, code: str) -> str:
        raise CloudStorageError("consent denied")

    monkeypatch.setattr("app.api.integrations.google_drive_exchange_code", _raise)

    callback_response = await admin_client.get(
        "/api/settings/storage-integrations/google-drive/oauth/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert callback_response.headers["location"] == "/integrations?error=google_drive"


# ------------------------------------------------------------------ onedrive


async def test_onedrive_oauth_start_requires_saved_credentials(admin_client: AsyncClient) -> None:
    response = await admin_client.get(
        "/api/settings/storage-integrations/onedrive/oauth/start", follow_redirects=False
    )
    assert response.status_code == 400


async def test_onedrive_oauth_start_redirects_to_the_authorize_url(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    await admin_client.put(
        "/api/settings/storage-integrations",
        json={"onedrive_client_id": "od-client", "onedrive_client_secret": "od-secret"},
    )
    monkeypatch.setattr(
        "app.api.integrations.onedrive_authorize_url",
        lambda client_id, _client_secret, _redirect_uri, state: (
            f"https://login.microsoftonline.com/authorize?client_id={client_id}&state={state}"
        ),
    )
    response = await admin_client.get(
        "/api/settings/storage-integrations/onedrive/oauth/start", follow_redirects=False
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert _query(location)["client_id"] == ["od-client"]


async def test_onedrive_oauth_callback_rejects_credentials_cleared_after_start(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    await admin_client.put(
        "/api/settings/storage-integrations",
        json={"onedrive_client_id": "od-client", "onedrive_client_secret": "od-secret"},
    )
    monkeypatch.setattr(
        "app.api.integrations.onedrive_authorize_url",
        lambda _client_id, _client_secret, _redirect_uri, state: (
            f"https://login.microsoftonline.com/?state={state}"
        ),
    )
    start_response = await admin_client.get(
        "/api/settings/storage-integrations/onedrive/oauth/start", follow_redirects=False
    )
    state = _query(start_response.headers["location"])["state"][0]

    await admin_client.put("/api/settings/storage-integrations", json={"onedrive_client_id": None})
    response = await admin_client.get(
        "/api/settings/storage-integrations/onedrive/oauth/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/integrations?error=onedrive"


async def test_onedrive_oauth_callback_completes_the_flow(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    await admin_client.put(
        "/api/settings/storage-integrations",
        json={"onedrive_client_id": "od-client", "onedrive_client_secret": "od-secret"},
    )
    monkeypatch.setattr(
        "app.api.integrations.onedrive_authorize_url",
        lambda _client_id, _client_secret, _redirect_uri, state: (
            f"https://login.microsoftonline.com/?state={state}"
        ),
    )
    start_response = await admin_client.get(
        "/api/settings/storage-integrations/onedrive/oauth/start", follow_redirects=False
    )
    state = _query(start_response.headers["location"])["state"][0]

    async def _fake_exchange(
        _client_id: str, _client_secret: str, _redirect_uri: str, code: str
    ) -> str:
        return "od-refresh-token"

    monkeypatch.setattr("app.api.integrations.onedrive_exchange_code", _fake_exchange)

    callback_response = await admin_client.get(
        "/api/settings/storage-integrations/onedrive/oauth/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    expected = "/integrations?connected=onedrive"
    assert callback_response.headers["location"] == expected

    settings_response = await admin_client.get("/api/settings/storage-integrations")
    assert settings_response.json()["onedrive_connected"] is True


async def test_onedrive_oauth_callback_rejects_a_missing_state(admin_client: AsyncClient) -> None:
    response = await admin_client.get(
        "/api/settings/storage-integrations/onedrive/oauth/callback",
        params={"code": "auth-code"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/integrations?error=onedrive"


async def test_onedrive_oauth_callback_wraps_exchange_errors(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    await admin_client.put(
        "/api/settings/storage-integrations",
        json={"onedrive_client_id": "od-client", "onedrive_client_secret": "od-secret"},
    )
    monkeypatch.setattr(
        "app.api.integrations.onedrive_authorize_url",
        lambda _client_id, _client_secret, _redirect_uri, state: (
            f"https://login.microsoftonline.com/?state={state}"
        ),
    )
    start_response = await admin_client.get(
        "/api/settings/storage-integrations/onedrive/oauth/start", follow_redirects=False
    )
    state = _query(start_response.headers["location"])["state"][0]

    async def _raise(client_id: str, client_secret: str, redirect_uri: str, code: str) -> str:
        raise CloudStorageError("token exchange failed")

    monkeypatch.setattr("app.api.integrations.onedrive_exchange_code", _raise)

    callback_response = await admin_client.get(
        "/api/settings/storage-integrations/onedrive/oauth/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert callback_response.headers["location"] == "/integrations?error=onedrive"
