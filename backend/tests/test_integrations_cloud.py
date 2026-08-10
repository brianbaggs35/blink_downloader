"""Cloud provider clients (S3/Google Drive/OneDrive): every network call is
faked at the SDK boundary (boto3 client, google-api-python-client service,
msal app, httpx transport) - never a real call to AWS/Google/Microsoft.
Trusts the official SDKs' own correctness; tests our glue and error
handling around them.
"""

# Same situation as app/integrations/cloud.py itself: these SDKs ship no
# type stubs.
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownParameterType=false
# pyright: reportMissingParameterType=false
# pyright: reportUnknownLambdaType=false

import base64
import hashlib
from typing import Any

import httplib2
import httpx
import pytest
from botocore.exceptions import ClientError
from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError as GoogleHttpError
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError

from app.integrations.cloud import (
    CloudStorageError,
    GoogleDriveClient,
    OneDriveClient,
    S3Client,
    google_drive_authorize_url,
    google_drive_exchange_code,
    onedrive_authorize_url,
    onedrive_exchange_code,
)

# ------------------------------------------------------------------------- S3


class _FakeBotoClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.raise_on: set[str] = set()
        self.presigned_url_value = "https://s3.example/signed"
        self.get_object_body = b"clip-bytes"
        self.list_objects_v2_response: dict[str, Any] = {"CommonPrefixes": []}

    def _maybe_raise(self, name: str) -> None:
        if name in self.raise_on:
            raise ClientError({"Error": {"Code": "Boom", "Message": "nope"}}, name)

    def put_object(self, **kwargs: Any) -> None:
        self.calls.append(("put_object", kwargs))
        self._maybe_raise("put_object")

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_object", kwargs))
        self._maybe_raise("get_object")

        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        return {"Body": _Body(self.get_object_body)}

    def delete_object(self, **kwargs: Any) -> None:
        self.calls.append(("delete_object", kwargs))
        self._maybe_raise("delete_object")

    def generate_presigned_url(self, *_args: Any, **kwargs: Any) -> str:
        self.calls.append(("generate_presigned_url", kwargs))
        self._maybe_raise("generate_presigned_url")
        return self.presigned_url_value

    def head_bucket(self, **kwargs: Any) -> None:
        self.calls.append(("head_bucket", kwargs))
        self._maybe_raise("head_bucket")

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_objects_v2", kwargs))
        self._maybe_raise("list_objects_v2")
        return self.list_objects_v2_response


def _s3_client(
    monkeypatch: pytest.MonkeyPatch, fake: _FakeBotoClient, **overrides: Any
) -> S3Client:
    monkeypatch.setattr("app.integrations.cloud.boto3.client", lambda *_a, **_kw: fake)
    return S3Client(
        access_key_id="AKIA",
        secret_access_key="secret",
        region="us-east-1",
        bucket="my-bucket",
        **overrides,
    )


async def test_s3_upload_uses_the_prefix_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    client = _s3_client(monkeypatch, fake, prefix="clips/2026")
    key = await client.upload("a.mp4", b"data")
    assert key == "clips/2026/a.mp4"
    assert fake.calls[0] == ("put_object", {"Bucket": "my-bucket", "Key": key, "Body": b"data"})


async def test_s3_upload_without_a_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    client = _s3_client(monkeypatch, fake)
    key = await client.upload("a.mp4", b"data")
    assert key == "a.mp4"


async def test_s3_upload_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.raise_on.add("put_object")
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="S3 upload failed"):
        await client.upload("a.mp4", b"data")


async def test_s3_download_returns_the_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.get_object_body = b"hello"
    client = _s3_client(monkeypatch, fake)
    assert await client.download("a.mp4") == b"hello"


async def test_s3_download_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.raise_on.add("get_object")
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="S3 download failed"):
        await client.download("a.mp4")


async def test_s3_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    client = _s3_client(monkeypatch, fake)
    await client.delete("a.mp4")
    assert fake.calls[0] == ("delete_object", {"Bucket": "my-bucket", "Key": "a.mp4"})


async def test_s3_delete_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.raise_on.add("delete_object")
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="S3 delete failed"):
        await client.delete("a.mp4")


async def test_s3_presigned_url(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.presigned_url_value = "https://s3.example/x"
    client = _s3_client(monkeypatch, fake)
    assert await client.presigned_url("a.mp4", 3600) == "https://s3.example/x"


async def test_s3_presigned_url_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.raise_on.add("generate_presigned_url")
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="S3 could not create a signed link"):
        await client.presigned_url("a.mp4", 3600)


async def test_s3_test_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    client = _s3_client(monkeypatch, fake)
    await client.test_connection()
    assert fake.calls[0] == ("head_bucket", {"Bucket": "my-bucket"})


async def test_s3_test_connection_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.raise_on.add("head_bucket")
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="Could not reach bucket"):
        await client.test_connection()


async def test_s3_list_folders_at_the_bucket_root(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.list_objects_v2_response = {
        "CommonPrefixes": [{"Prefix": "clips/"}, {"Prefix": "backups/"}]
    }
    client = _s3_client(monkeypatch, fake)
    folders = await client.list_folders()
    assert folders == [("clips", "clips"), ("backups", "backups")]
    assert fake.calls[0] == (
        "list_objects_v2",
        {"Bucket": "my-bucket", "Prefix": "", "Delimiter": "/"},
    )


async def test_s3_list_folders_under_a_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.list_objects_v2_response = {"CommonPrefixes": [{"Prefix": "clips/2026/"}]}
    client = _s3_client(monkeypatch, fake)
    folders = await client.list_folders("clips")
    assert folders == [("clips/2026", "2026")]
    assert fake.calls[0][1]["Prefix"] == "clips/"


async def test_s3_list_folders_with_none_at_this_level(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    client = _s3_client(monkeypatch, fake)
    assert await client.list_folders() == []


async def test_s3_list_folders_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.raise_on.add("list_objects_v2")
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="S3 could not list folders"):
        await client.list_folders()


async def test_s3_create_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    client = _s3_client(monkeypatch, fake)
    path = await client.create_folder("clips/2026")
    assert path == "clips/2026"
    assert fake.calls[0] == (
        "put_object",
        {"Bucket": "my-bucket", "Key": "clips/2026/", "Body": b""},
    )


async def test_s3_create_folder_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.raise_on.add("put_object")
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="S3 could not create folder"):
        await client.create_folder("clips")


async def test_s3_rename_folder_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.list_objects_v2_response = {"Contents": [{"Key": "clips/garage/"}]}
    client = _s3_client(monkeypatch, fake)
    new_path = await client.rename_folder("clips/garage", "driveway")
    assert new_path == "clips/driveway"
    put_calls = [call for call in fake.calls if call[0] == "put_object"]
    assert put_calls[-1][1] == {"Bucket": "my-bucket", "Key": "clips/driveway/", "Body": b""}
    delete_calls = [call for call in fake.calls if call[0] == "delete_object"]
    assert delete_calls[-1][1] == {"Bucket": "my-bucket", "Key": "clips/garage/"}


async def test_s3_rename_folder_at_the_bucket_root(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.list_objects_v2_response = {"Contents": [{"Key": "garage/"}]}
    client = _s3_client(monkeypatch, fake)
    new_path = await client.rename_folder("garage", "driveway")
    assert new_path == "driveway"


async def test_s3_rename_folder_refuses_when_not_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.list_objects_v2_response = {
        "Contents": [{"Key": "clips/garage/"}, {"Key": "clips/garage/x.mp4"}]
    }
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="isn't empty"):
        await client.rename_folder("clips/garage", "driveway")


async def test_s3_rename_folder_wraps_the_emptiness_check_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeBotoClient()
    fake.raise_on.add("list_objects_v2")
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="S3 could not check folder contents"):
        await client.rename_folder("clips/garage", "driveway")


async def test_s3_rename_folder_wraps_the_delete_marker_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeBotoClient()
    fake.list_objects_v2_response = {"Contents": [{"Key": "clips/garage/"}]}
    fake.raise_on.add("delete_object")
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="could not remove the old folder marker"):
        await client.rename_folder("clips/garage", "driveway")


async def test_s3_delete_folder_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.list_objects_v2_response = {"Contents": [{"Key": "clips/garage/"}]}
    client = _s3_client(monkeypatch, fake)
    await client.delete_folder("clips/garage")
    delete_calls = [call for call in fake.calls if call[0] == "delete_object"]
    assert delete_calls[-1][1] == {"Bucket": "my-bucket", "Key": "clips/garage/"}


async def test_s3_delete_folder_refuses_when_not_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.list_objects_v2_response = {
        "Contents": [{"Key": "clips/garage/"}, {"Key": "clips/garage/x.mp4"}]
    }
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="isn't empty"):
        await client.delete_folder("clips/garage")


async def test_s3_delete_folder_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeBotoClient()
    fake.list_objects_v2_response = {"Contents": [{"Key": "clips/garage/"}]}
    fake.raise_on.add("delete_object")
    client = _s3_client(monkeypatch, fake)
    with pytest.raises(CloudStorageError, match="S3 delete failed"):
        await client.delete_folder("clips/garage")


# ------------------------------------------------------------- Google Drive


class _FakeFlow:
    def __init__(
        self,
        *,
        refresh_token: str | None = "refresh-abc",  # noqa: S107 # nosec B107 - test fixture value, not a secret
        raise_on_fetch: bool = False,
        code_verifier: str | None = "fake-verifier",
    ) -> None:
        self.raise_on_fetch = raise_on_fetch
        self.fetched_code: str | None = None
        self.code_verifier = code_verifier

        class _Creds:
            def __init__(self, token: str | None) -> None:
                self.refresh_token = token

        self.credentials = _Creds(refresh_token)

    def authorization_url(self, **kwargs: Any) -> tuple[str, str]:
        return f"https://accounts.google.com/authorize?state={kwargs.get('state')}", "unused"

    def fetch_token(self, *, code: str) -> None:
        if self.raise_on_fetch:
            # The real failure mode this guards: oauthlib's own OAuth2Error
            # family (e.g. a PKCE code_verifier mismatch), not
            # google-auth's GoogleAuthError - confirmed these are two
            # unrelated exception hierarchies by reproducing the real
            # "Missing code verifier" InvalidGrantError empirically against
            # the actual oauthlib/google-auth-oauthlib stack.
            raise InvalidGrantError("Missing code verifier.")
        self.fetched_code = code


def test_google_drive_authorize_url_includes_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.cloud._google_flow", lambda *_a, **_kw: _FakeFlow())
    url, code_verifier = google_drive_authorize_url(
        "client-id", "secret", "https://app.example/cb", "state-123"
    )
    assert "state=state-123" in url
    assert code_verifier == "fake-verifier"


def test_google_flow_builds_a_real_flow_from_client_config() -> None:
    """Exercises the real google_auth_oauthlib.flow.Flow (not the fake) -
    building the Flow and rendering its authorization_url() are both pure
    local URL construction with no network call, so this is safe to run
    unmocked and gives real coverage of the client_config wiring itself,
    including that the returned code_verifier really does correspond to
    the URL's own code_challenge (the crux of the PKCE bug this guards)."""
    url, code_verifier = google_drive_authorize_url(
        "client-id", "client-secret", "https://app.example/cb", "state-xyz"
    )
    assert url.startswith("https://accounts.google.com/o/oauth2/auth")
    assert "client_id=client-id" in url
    assert "state=state-xyz" in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert f"code_challenge={expected_challenge}" in url


async def test_google_drive_exchange_code_returns_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_google_flow(*args: Any, **kwargs: Any) -> _FakeFlow:
        captured["code_verifier"] = kwargs.get("code_verifier")
        return _FakeFlow(refresh_token="rt-1")

    monkeypatch.setattr("app.integrations.cloud._google_flow", fake_google_flow)
    token = await google_drive_exchange_code(
        "id", "secret", "https://app.example/cb", "code-1", "verifier-xyz"
    )
    assert token == "rt-1"
    # The exact fix: the exchange must rebuild its Flow with the *same*
    # verifier the authorize step produced, not a fresh/unrelated one.
    assert captured["code_verifier"] == "verifier-xyz"


async def test_google_drive_exchange_code_raises_without_a_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.integrations.cloud._google_flow", lambda *_a, **_kw: _FakeFlow(refresh_token=None)
    )
    with pytest.raises(CloudStorageError, match="did not return a refresh token"):
        await google_drive_exchange_code(
            "id", "secret", "https://app.example/cb", "code-1", "verifier-xyz"
        )


async def test_google_drive_exchange_code_wraps_oauth2_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real-world failure this whole fix targets: a PKCE mismatch
    raises oauthlib's InvalidGrantError (an OAuth2Error), not a
    GoogleAuthError - must still surface as this app's own
    CloudStorageError, not an unhandled 500."""
    monkeypatch.setattr(
        "app.integrations.cloud._google_flow", lambda *_a, **_kw: _FakeFlow(raise_on_fetch=True)
    )
    with pytest.raises(CloudStorageError, match="authorization failed"):
        await google_drive_exchange_code(
            "id", "secret", "https://app.example/cb", "code-1", "verifier-xyz"
        )


async def test_google_drive_exchange_code_wraps_google_auth_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GoogleAuthError (a completely separate hierarchy from oauthlib's
    OAuth2Error) must still also be caught - this was the only exception
    type caught before this fix broadened it."""

    class _RaisingFlow(_FakeFlow):
        def fetch_token(self, *, code: str) -> None:
            raise GoogleAuthError("bad code")

    monkeypatch.setattr("app.integrations.cloud._google_flow", lambda *_a, **_kw: _RaisingFlow())
    with pytest.raises(CloudStorageError, match="authorization failed"):
        await google_drive_exchange_code(
            "id", "secret", "https://app.example/cb", "code-1", "verifier-xyz"
        )


class _FakeGoogleRequest:
    def __init__(self, chunks: list[tuple[Any, Any]]) -> None:
        self._chunks = list(chunks)

    def next_chunk(self) -> tuple[Any, Any]:
        return self._chunks.pop(0)


class _FakeExecuteRequest:
    def __init__(self, result: Any = None, raise_error: bool = False) -> None:
        self._result = result or {}
        self._raise_error = raise_error

    def execute(self) -> Any:
        if self._raise_error:
            raise GoogleHttpError(httplib2.Response({"status": "500"}), b"boom")
        return self._result


class _FakeFilesResource:
    def __init__(self, drive: Any) -> None:
        self._drive = drive

    def create(self, *, body: Any, media_body: Any = None, fields: str) -> Any:
        self._drive.create_calls.append(body)
        if media_body is None:
            # Folder creation has no media to upload - a plain, immediate
            # execute() rather than the resumable next_chunk() loop below.
            return _FakeExecuteRequest(
                result={"id": self._drive.created_folder_id},
                raise_error=self._drive.raise_on_create,
            )
        return _FakeGoogleRequest(list(self._drive.upload_chunks))

    def get_media(self, *, fileId: str) -> _FakeGoogleRequest:  # noqa: N803 - matches googleapiclient's own kwarg name
        self._drive.get_media_calls.append(fileId)
        return _FakeGoogleRequest([])

    def delete(self, *, fileId: str) -> _FakeExecuteRequest:  # noqa: N803
        self._drive.delete_calls.append(fileId)
        return _FakeExecuteRequest(raise_error=self._drive.raise_on_delete)

    def list(self, *, q: str, fields: str, spaces: str) -> _FakeExecuteRequest:
        self._drive.list_queries.append(q)
        return _FakeExecuteRequest(
            result={"files": self._drive.list_files_response},
            raise_error=self._drive.raise_on_list,
        )

    def update(self, *, fileId: str, body: dict[str, Any]) -> _FakeExecuteRequest:  # noqa: N803
        self._drive.update_calls.append((fileId, body))
        return _FakeExecuteRequest(raise_error=self._drive.raise_on_update)


class _FakeAboutResource:
    def __init__(self, drive: Any) -> None:
        self._drive = drive

    def get(self, *, fields: str) -> _FakeExecuteRequest:
        return _FakeExecuteRequest(raise_error=self._drive.raise_on_about)


class _FakeDriveService:
    def __init__(self) -> None:
        self.upload_chunks: list[tuple[Any, Any]] = [(None, {"id": "file-123"})]
        self.raise_on_delete = False
        self.raise_on_about = False
        self.raise_on_create = False
        self.raise_on_list = False
        self.raise_on_update = False
        self.created_folder_id = "new-folder-1"
        self.list_files_response: list[dict[str, str]] = []
        self.create_calls: list[Any] = []
        self.get_media_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.list_queries: list[str] = []
        self.update_calls: list[tuple[str, dict[str, Any]]] = []

    def files(self) -> _FakeFilesResource:
        return _FakeFilesResource(self)

    def about(self) -> _FakeAboutResource:
        return _FakeAboutResource(self)


def _drive_client(
    monkeypatch: pytest.MonkeyPatch, drive: _FakeDriveService, **kwargs: Any
) -> GoogleDriveClient:
    monkeypatch.setattr("app.integrations.cloud.build_drive_service", lambda *_a, **_kw: drive)
    return GoogleDriveClient(client_id="id", client_secret="secret", refresh_token="rt", **kwargs)


class _FakeDownloader:
    def __init__(self, fd: Any, request: Any) -> None:
        self._fd = fd

    def next_chunk(self) -> tuple[Any, bool]:
        self._fd.write(b"downloaded-bytes")
        return None, True


async def test_google_drive_upload_includes_folder_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drive = _FakeDriveService()
    client = _drive_client(monkeypatch, drive, folder_id="folder-1")
    file_id = await client.upload("a.mp4", b"data")
    assert file_id == "file-123"
    assert drive.create_calls[0]["parents"] == ["folder-1"]


async def test_google_drive_upload_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()

    class _RaisingFiles(_FakeFilesResource):
        def create(self, *, body: Any, media_body: Any = None, fields: str) -> _FakeGoogleRequest:
            raise GoogleHttpError(httplib2.Response({"status": "500"}), b"boom")

    drive.files = lambda: _RaisingFiles(drive)  # type: ignore[method-assign]
    client = _drive_client(monkeypatch, drive)
    with pytest.raises(CloudStorageError, match="Google Drive upload failed"):
        await client.upload("a.mp4", b"data")


async def test_google_drive_download(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.cloud.MediaIoBaseDownload", _FakeDownloader)
    drive = _FakeDriveService()
    client = _drive_client(monkeypatch, drive)
    assert await client.download("file-123") == b"downloaded-bytes"
    assert drive.get_media_calls == ["file-123"]


async def test_google_drive_download_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _RaisingDownloader:
        def __init__(self, fd: Any, request: Any) -> None:
            pass

        def next_chunk(self) -> tuple[Any, bool]:
            raise GoogleHttpError(httplib2.Response({"status": "404"}), b"missing")

    monkeypatch.setattr("app.integrations.cloud.MediaIoBaseDownload", _RaisingDownloader)
    drive = _FakeDriveService()
    client = _drive_client(monkeypatch, drive)
    with pytest.raises(CloudStorageError, match="Google Drive download failed"):
        await client.download("file-123")


async def test_google_drive_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    client = _drive_client(monkeypatch, drive)
    await client.delete("file-123")
    assert drive.delete_calls == ["file-123"]


async def test_google_drive_delete_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    drive.raise_on_delete = True
    client = _drive_client(monkeypatch, drive)
    with pytest.raises(CloudStorageError, match="Google Drive delete failed"):
        await client.delete("file-123")


async def test_google_drive_test_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    client = _drive_client(monkeypatch, drive)
    await client.test_connection()


async def test_google_drive_test_connection_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    drive.raise_on_about = True
    client = _drive_client(monkeypatch, drive)
    with pytest.raises(CloudStorageError, match="Could not reach Google Drive"):
        await client.test_connection()


async def test_google_drive_list_folders_defaults_to_the_drive_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drive = _FakeDriveService()
    drive.list_files_response = [{"id": "f1", "name": "Clips"}, {"id": "f2", "name": "Backups"}]
    client = _drive_client(monkeypatch, drive)
    folders = await client.list_folders()
    assert folders == [("f1", "Clips"), ("f2", "Backups")]
    assert "'root' in parents" in drive.list_queries[0]


async def test_google_drive_list_folders_under_a_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    drive.list_files_response = [{"id": "f3", "name": "2026"}]
    client = _drive_client(monkeypatch, drive)
    folders = await client.list_folders("f1")
    assert folders == [("f3", "2026")]
    assert "'f1' in parents" in drive.list_queries[0]


async def test_google_drive_list_folders_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    drive.raise_on_list = True
    client = _drive_client(monkeypatch, drive)
    with pytest.raises(CloudStorageError, match="Google Drive could not list folders"):
        await client.list_folders()


async def test_google_drive_create_folder_at_the_root(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    drive.created_folder_id = "new-folder-42"
    client = _drive_client(monkeypatch, drive)
    folder_id = await client.create_folder(None, "New Folder")
    assert folder_id == "new-folder-42"
    assert drive.create_calls[0] == {
        "name": "New Folder",
        "mimeType": "application/vnd.google-apps.folder",
    }


async def test_google_drive_create_folder_under_a_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    client = _drive_client(monkeypatch, drive)
    await client.create_folder("f1", "Subfolder")
    assert drive.create_calls[0]["parents"] == ["f1"]


async def test_google_drive_create_folder_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    drive.raise_on_create = True
    client = _drive_client(monkeypatch, drive)
    with pytest.raises(CloudStorageError, match="Google Drive could not create folder"):
        await client.create_folder(None, "New Folder")


async def test_google_drive_rename_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    client = _drive_client(monkeypatch, drive)
    await client.rename_folder("folder-1", "Renamed")
    assert drive.update_calls == [("folder-1", {"name": "Renamed"})]


async def test_google_drive_rename_folder_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    drive.raise_on_update = True
    client = _drive_client(monkeypatch, drive)
    with pytest.raises(CloudStorageError, match="Google Drive could not rename folder"):
        await client.rename_folder("folder-1", "Renamed")


async def test_google_drive_delete_folder_trashes_rather_than_hard_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drive = _FakeDriveService()
    client = _drive_client(monkeypatch, drive)
    await client.delete_folder("folder-1")
    assert drive.update_calls == [("folder-1", {"trashed": True})]
    assert drive.delete_calls == []


async def test_google_drive_delete_folder_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    drive = _FakeDriveService()
    drive.raise_on_update = True
    client = _drive_client(monkeypatch, drive)
    with pytest.raises(CloudStorageError, match="Google Drive could not delete folder"):
        await client.delete_folder("folder-1")


# ------------------------------------------------------------------ OneDrive


class _FakeMsalApp:
    def __init__(self, *, token_result: dict[str, Any] | None = None) -> None:
        self.token_result = token_result if token_result is not None else {"access_token": "at-1"}

    def get_authorization_request_url(self, scopes: list[str], **kwargs: Any) -> str:
        return f"https://login.microsoftonline.com/authorize?state={kwargs.get('state')}"

    def acquire_token_by_authorization_code(self, code: str, **kwargs: Any) -> dict[str, Any]:
        return self.token_result

    def acquire_token_by_refresh_token(self, refresh_token: str, **kwargs: Any) -> dict[str, Any]:
        return self.token_result


def test_onedrive_authorize_url_includes_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.cloud._onedrive_app", lambda *_a, **_kw: _FakeMsalApp())
    url = onedrive_authorize_url("id", "secret", "https://app.example/cb", "state-xyz")
    assert "state=state-xyz" in url


async def test_onedrive_exchange_code_returns_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.integrations.cloud._onedrive_app",
        lambda *_a, **_kw: _FakeMsalApp(token_result={"refresh_token": "rt-2"}),
    )
    token = await onedrive_exchange_code("id", "secret", "https://app.example/cb", "code-1")
    assert token == "rt-2"


async def test_onedrive_exchange_code_raises_without_a_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.integrations.cloud._onedrive_app",
        lambda *_a, **_kw: _FakeMsalApp(token_result={"error_description": "denied"}),
    )
    with pytest.raises(CloudStorageError, match="denied"):
        await onedrive_exchange_code("id", "secret", "https://app.example/cb", "code-1")


async def test_onedrive_exchange_code_wraps_authority_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_onedrive_app() can perform authority validation against
    Microsoft's endpoint during construction - msal's own Authority class
    raises a plain ValueError when that discovery call fails (confirmed by
    reading its source), which must surface as this app's own
    CloudStorageError rather than an unhandled 500, the same "uncaught
    exception past the app's own error wrapping" shape as the Google Drive
    PKCE bug."""

    def _raise_authority_error(*_a: Any, **_kw: Any) -> _FakeMsalApp:
        raise ValueError("Unable to get authority configuration for https://example.com/bad.")

    monkeypatch.setattr("app.integrations.cloud._onedrive_app", _raise_authority_error)
    with pytest.raises(CloudStorageError, match="OneDrive authorization failed"):
        await onedrive_exchange_code("id", "secret", "https://app.example/cb", "code-1")


def _onedrive_client(
    monkeypatch: pytest.MonkeyPatch, msal_app: _FakeMsalApp, **kwargs: Any
) -> OneDriveClient:
    monkeypatch.setattr("app.integrations.cloud._onedrive_app", lambda *_a, **_kw: msal_app)
    return OneDriveClient(client_id="id", client_secret="secret", refresh_token="rt", **kwargs)


def _patch_graph_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    """Patches httpx.AsyncClient globally for the duration of the test -
    same pattern as test_alerts_delivery.py, since OneDriveClient's Graph
    calls (unlike alerts' send_* functions) don't accept an injected client."""
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kw: real_async_client(transport=httpx.MockTransport(handler)),
    )


async def test_onedrive_access_token_raises_without_one(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp(token_result={"error_description": "expired"})
    client = _onedrive_client(monkeypatch, msal_app)
    with pytest.raises(CloudStorageError, match="expired"):
        await client.test_connection()


async def test_onedrive_upload_single_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app, folder_path="Clips")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("createUploadSession"):
            return httpx.Response(200, json={"uploadUrl": "https://upload.example/session1"})
        return httpx.Response(200, json={"id": "item-1"})

    _patch_graph_transport(monkeypatch, handler)
    file_id = await client.upload("a.mp4", b"small-clip-body")
    assert file_id == "item-1"


async def test_onedrive_upload_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    _patch_graph_transport(monkeypatch, handler)
    with pytest.raises(CloudStorageError, match="OneDrive upload failed"):
        await client.upload("a.mp4", b"data")


async def test_onedrive_download(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"onedrive-bytes")

    _patch_graph_transport(monkeypatch, handler)
    assert await client.download("item-1") == b"onedrive-bytes"


async def test_onedrive_download_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    _patch_graph_transport(monkeypatch, handler)
    with pytest.raises(CloudStorageError, match="OneDrive download failed"):
        await client.download("item-1")


async def test_onedrive_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        return httpx.Response(204)

    _patch_graph_transport(monkeypatch, handler)
    await client.delete("item-1")
    assert captured["method"] == "DELETE"


async def test_onedrive_delete_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    _patch_graph_transport(monkeypatch, handler)
    with pytest.raises(CloudStorageError, match="OneDrive delete failed"):
        await client.delete("item-1")


async def test_onedrive_test_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "drive-1"})

    _patch_graph_transport(monkeypatch, handler)
    await client.test_connection()


async def test_onedrive_test_connection_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    _patch_graph_transport(monkeypatch, handler)
    with pytest.raises(CloudStorageError, match="Could not reach OneDrive"):
        await client.test_connection()


async def test_onedrive_list_folders_defaults_to_the_drive_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "value": [
                    {"id": "f1", "name": "Clips", "folder": {}},
                    {"id": "file1", "name": "not-a-folder.mp4"},
                ]
            },
        )

    _patch_graph_transport(monkeypatch, handler)
    folders = await client.list_folders()
    assert folders == [("f1", "Clips")]
    assert captured["path"].endswith("/root/children")


async def test_onedrive_list_folders_under_a_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json={"value": [{"id": "f2", "name": "2026", "folder": {}}]})

    _patch_graph_transport(monkeypatch, handler)
    folders = await client.list_folders("f1")
    assert folders == [("f2", "2026")]
    assert captured["path"].endswith("/items/f1/children")


async def test_onedrive_list_folders_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    _patch_graph_transport(monkeypatch, handler)
    with pytest.raises(CloudStorageError, match="OneDrive could not list folders"):
        await client.list_folders()


async def test_onedrive_create_folder_at_the_root(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content
        return httpx.Response(201, json={"id": "new-folder-1"})

    _patch_graph_transport(monkeypatch, handler)
    folder_id = await client.create_folder(None, "New Folder")
    assert folder_id == "new-folder-1"
    assert captured["path"].endswith("/root/children")
    assert b"New Folder" in captured["body"]


async def test_onedrive_create_folder_under_a_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(201, json={"id": "new-folder-2"})

    _patch_graph_transport(monkeypatch, handler)
    await client.create_folder("f1", "Subfolder")
    assert captured["path"].endswith("/items/f1/children")


async def test_onedrive_create_folder_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    _patch_graph_transport(monkeypatch, handler)
    with pytest.raises(CloudStorageError, match="OneDrive could not create folder"):
        await client.create_folder(None, "New Folder")


async def test_onedrive_rename_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = request.content
        return httpx.Response(200, json={"id": "item-1", "name": "Driveway"})

    _patch_graph_transport(monkeypatch, handler)
    await client.rename_folder("item-1", "Driveway")
    assert captured["method"] == "PATCH"
    assert captured["path"].endswith("/items/item-1")
    assert b"Driveway" in captured["body"]


async def test_onedrive_rename_folder_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    _patch_graph_transport(monkeypatch, handler)
    with pytest.raises(CloudStorageError, match="OneDrive could not rename folder"):
        await client.rename_folder("item-1", "Driveway")


async def test_onedrive_delete_folder_reuses_the_recycle_bin_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(204)

    _patch_graph_transport(monkeypatch, handler)
    await client.delete_folder("item-1")
    assert captured["method"] == "DELETE"
    assert captured["path"].endswith("/items/item-1")


async def test_onedrive_delete_folder_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    msal_app = _FakeMsalApp()
    client = _onedrive_client(monkeypatch, msal_app)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    _patch_graph_transport(monkeypatch, handler)
    with pytest.raises(CloudStorageError, match="OneDrive delete failed"):
        await client.delete_folder("item-1")
