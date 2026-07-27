"""Thin clients for the three archive destinations.

Each provider uses its official SDK for the fiddly, security-sensitive
parts (SigV4 signing, OAuth token exchange/refresh) rather than
hand-rolled HTTP: boto3 for S3, google-auth-oauthlib + google-api-python-
client for Google Drive, and msal for OneDrive's token lifecycle. OneDrive
file operations still go through Microsoft Graph directly via httpx -
Microsoft has no separate "OneDrive files" SDK; calling Graph with a
msal-acquired token is their own documented pattern, not a shortcut.

None of these clients ever see a plaintext credential from the database -
callers decrypt just before constructing one (see app.integrations.service).
"""

# boto3/google-api-python-client/msal ship no type stubs (no py.typed
# marker), same situation as blinkpy elsewhere in this codebase.
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownParameterType=false
# pyright: reportMissingParameterType=false

import asyncio
import io
from typing import Any, Protocol

import boto3
import httpx
import msal
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from google.auth.exceptions import GoogleAuthError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build as build_drive_service
from googleapiclient.errors import HttpError as GoogleHttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 # nosec B105 - a URL, not a secret
GOOGLE_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

MS_AUTHORITY = "https://login.microsoftonline.com/common"
MS_GRAPH_SCOPES = ["Files.ReadWrite"]
GRAPH_API_URL = "https://graph.microsoft.com/v1.0"

DEFAULT_ONEDRIVE_FOLDER = "BlinkClips"
ONEDRIVE_UPLOAD_CHUNK_BYTES = 10 * 1024 * 1024
UPLOAD_CHUNK_SIZE_BYTES = 5 * 1024 * 1024


class CloudStorageError(Exception):
    """A cloud provider upload/download/delete/link/auth operation failed."""


class CloudClient(Protocol):
    """Structural shape shared by S3Client/GoogleDriveClient/OneDriveClient
    - enough for archive/restore orchestration (app.integrations.archive)
    to work with whichever provider a clip is archived to without a
    per-provider branch at every call site. S3-only extras (presigned_url)
    are deliberately not part of this shape; callers narrow to S3Client
    directly for those. Parameters are positional-only so each
    implementation can keep its own more descriptive name (file_id,
    item_id, key, ...) without breaking structural compatibility."""

    async def upload(self, name: str, data: bytes, /) -> str: ...

    async def download(self, key: str, /) -> bytes: ...

    async def delete(self, key: str, /) -> None: ...

    async def test_connection(self) -> None: ...


# --------------------------------------------------------------------- S3


class S3Client:
    def __init__(
        self,
        *,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        bucket: str,
        prefix: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/") if prefix else None
        self._client = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            # Explicit, not relying on botocore's default: SigV4 everywhere
            # (SigV2 is deprecated/unsupported by AWS) and HTTPS-only.
            config=BotoConfig(signature_version="s3v4"),
            use_ssl=True,
        )

    def _key(self, name: str) -> str:
        return f"{self._prefix}/{name}" if self._prefix else name

    async def upload(self, name: str, data: bytes) -> str:
        key = self._key(name)
        try:
            await asyncio.to_thread(
                self._client.put_object, Bucket=self._bucket, Key=key, Body=data
            )
        except (BotoCoreError, ClientError) as exc:
            raise CloudStorageError(f"S3 upload failed: {exc}") from exc
        return key

    async def download(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
            return await asyncio.to_thread(response["Body"].read)
        except (BotoCoreError, ClientError) as exc:
            raise CloudStorageError(f"S3 download failed: {exc}") from exc

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise CloudStorageError(f"S3 delete failed: {exc}") from exc

    async def presigned_url(self, key: str, expires_in: int) -> str:
        try:
            return await asyncio.to_thread(
                self._client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError) as exc:
            raise CloudStorageError(f"S3 could not create a signed link: {exc}") from exc

    async def test_connection(self) -> None:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except (BotoCoreError, ClientError) as exc:
            raise CloudStorageError(f"Could not reach bucket '{self._bucket}': {exc}") from exc


# ------------------------------------------------------------- Google Drive


def _google_flow(client_id: str, client_secret: str, redirect_uri: str) -> Flow:
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_OAUTH_TOKEN_ENDPOINT,
            "redirect_uris": [redirect_uri],
        }
    }
    return Flow.from_client_config(
        client_config, scopes=GOOGLE_DRIVE_SCOPES, redirect_uri=redirect_uri
    )


def google_drive_authorize_url(
    client_id: str, client_secret: str, redirect_uri: str, state: str
) -> str:
    flow = _google_flow(client_id, client_secret, redirect_uri)
    # offline + consent guarantees a refresh_token even if this app was
    # already authorized before (Google otherwise omits it on repeat
    # consent).
    authorize_url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state)
    return str(authorize_url)


def _exchange_google_code_sync(
    client_id: str, client_secret: str, redirect_uri: str, code: str
) -> str:
    flow = _google_flow(client_id, client_secret, redirect_uri)
    try:
        flow.fetch_token(code=code)
    except GoogleAuthError as exc:
        raise CloudStorageError(f"Google Drive authorization failed: {exc}") from exc
    refresh_token = flow.credentials.refresh_token
    if not refresh_token:
        raise CloudStorageError(
            "Google did not return a refresh token. Revoke this app's access at "
            "https://myaccount.google.com/permissions and try connecting again."
        )
    return str(refresh_token)


async def google_drive_exchange_code(
    client_id: str, client_secret: str, redirect_uri: str, code: str
) -> str:
    """Exchanges an OAuth authorization code for a refresh token."""
    return await asyncio.to_thread(
        _exchange_google_code_sync, client_id, client_secret, redirect_uri, code
    )


class GoogleDriveClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        folder_id: str | None = None,
    ) -> None:
        self._credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri=GOOGLE_OAUTH_TOKEN_ENDPOINT,
            scopes=GOOGLE_DRIVE_SCOPES,
        )
        self._folder_id = folder_id

    def _service(self) -> Any:
        # A fresh service per call - google-api-python-client's discovery
        # objects aren't documented as thread-safe, and every call here
        # already runs on its own asyncio.to_thread worker thread.
        return build_drive_service("drive", "v3", credentials=self._credentials)

    def _upload_sync(self, name: str, data: bytes) -> str:
        metadata: dict[str, Any] = {"name": name}
        if self._folder_id:
            metadata["parents"] = [self._folder_id]
        media = MediaIoBaseUpload(
            io.BytesIO(data),
            mimetype="video/mp4",
            chunksize=UPLOAD_CHUNK_SIZE_BYTES,
            resumable=True,
        )
        request = self._service().files().create(body=metadata, media_body=media, fields="id")
        response = None
        while response is None:
            _, response = request.next_chunk()
        return str(response["id"])

    async def upload(self, name: str, data: bytes) -> str:
        try:
            return await asyncio.to_thread(self._upload_sync, name, data)
        except (GoogleHttpError, GoogleAuthError) as exc:
            raise CloudStorageError(f"Google Drive upload failed: {exc}") from exc

    def _download_sync(self, file_id: str) -> bytes:
        buffer = io.BytesIO()
        request = self._service().files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    async def download(self, file_id: str) -> bytes:
        try:
            return await asyncio.to_thread(self._download_sync, file_id)
        except (GoogleHttpError, GoogleAuthError) as exc:
            raise CloudStorageError(f"Google Drive download failed: {exc}") from exc

    def _delete_sync(self, file_id: str) -> None:
        self._service().files().delete(fileId=file_id).execute()

    async def delete(self, file_id: str) -> None:
        try:
            await asyncio.to_thread(self._delete_sync, file_id)
        except (GoogleHttpError, GoogleAuthError) as exc:
            raise CloudStorageError(f"Google Drive delete failed: {exc}") from exc

    def _test_connection_sync(self) -> None:
        self._service().about().get(fields="user").execute()

    async def test_connection(self) -> None:
        try:
            await asyncio.to_thread(self._test_connection_sync)
        except (GoogleHttpError, GoogleAuthError) as exc:
            raise CloudStorageError(f"Could not reach Google Drive: {exc}") from exc


# ------------------------------------------------------------------ OneDrive


def _onedrive_app(client_id: str, client_secret: str) -> msal.ConfidentialClientApplication:
    # Always mocked in tests (app.integrations.cloud._onedrive_app): unlike
    # _google_flow, constructing the real MSAL app may perform authority
    # validation against Microsoft's endpoint, so exercising this
    # unmocked would make the test suite depend on live network access.
    return msal.ConfidentialClientApplication(  # pragma: no cover
        client_id, client_credential=client_secret, authority=MS_AUTHORITY
    )


def onedrive_authorize_url(
    client_id: str, client_secret: str, redirect_uri: str, state: str
) -> str:
    app = _onedrive_app(client_id, client_secret)
    scopes = [*MS_GRAPH_SCOPES, "offline_access"]
    return str(app.get_authorization_request_url(scopes, redirect_uri=redirect_uri, state=state))


def _exchange_onedrive_code_sync(
    client_id: str, client_secret: str, redirect_uri: str, code: str
) -> str:
    app = _onedrive_app(client_id, client_secret)
    result = app.acquire_token_by_authorization_code(
        code, scopes=MS_GRAPH_SCOPES, redirect_uri=redirect_uri
    )
    refresh_token = result.get("refresh_token")
    if not refresh_token:
        detail = result.get("error_description", "Microsoft did not return a refresh token.")
        raise CloudStorageError(f"OneDrive authorization failed: {detail}")
    return str(refresh_token)


async def onedrive_exchange_code(
    client_id: str, client_secret: str, redirect_uri: str, code: str
) -> str:
    return await asyncio.to_thread(
        _exchange_onedrive_code_sync, client_id, client_secret, redirect_uri, code
    )


class OneDriveClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        folder_path: str | None = None,
    ) -> None:
        self._app = _onedrive_app(client_id, client_secret)
        self._refresh_token = refresh_token
        self._folder_path = (folder_path or DEFAULT_ONEDRIVE_FOLDER).strip("/")

    def _access_token_sync(self) -> str:
        result = self._app.acquire_token_by_refresh_token(
            self._refresh_token, scopes=MS_GRAPH_SCOPES
        )
        token = result.get("access_token")
        if not token:
            detail = result.get("error_description", "Could not refresh OneDrive access.")
            raise CloudStorageError(detail)
        return str(token)

    async def _access_token(self) -> str:
        return await asyncio.to_thread(self._access_token_sync)

    def _item_path(self, name: str) -> str:
        return f"{self._folder_path}/{name}"

    async def upload(self, name: str, data: bytes) -> str:
        """Uploads via a resumable session - clips routinely exceed Microsoft
        Graph's 4MB simple-upload limit."""
        token = await self._access_token()
        path = self._item_path(name)
        result: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                session_response = await client.post(
                    f"{GRAPH_API_URL}/me/drive/root:/{path}:/createUploadSession",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"item": {"@microsoft.graph.conflictBehavior": "replace"}},
                )
                session_response.raise_for_status()
                upload_url = session_response.json()["uploadUrl"]

                total = len(data)
                for start in range(0, total, ONEDRIVE_UPLOAD_CHUNK_BYTES):
                    chunk = data[start : start + ONEDRIVE_UPLOAD_CHUNK_BYTES]
                    end = start + len(chunk) - 1
                    chunk_response = await client.put(
                        upload_url,
                        headers={
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {start}-{end}/{total}",
                        },
                        content=chunk,
                    )
                    chunk_response.raise_for_status()
                    result = chunk_response.json()
            except httpx.HTTPError as exc:
                raise CloudStorageError(f"OneDrive upload failed: {exc}") from exc
        return str(result["id"])

    async def download(self, item_id: str) -> bytes:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                response = await client.get(
                    f"{GRAPH_API_URL}/me/drive/items/{item_id}/content",
                    headers={"Authorization": f"Bearer {token}"},
                    follow_redirects=True,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise CloudStorageError(f"OneDrive download failed: {exc}") from exc
        return response.content

    async def delete(self, item_id: str) -> None:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.delete(
                    f"{GRAPH_API_URL}/me/drive/items/{item_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise CloudStorageError(f"OneDrive delete failed: {exc}") from exc

    async def test_connection(self) -> None:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(
                    f"{GRAPH_API_URL}/me/drive",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise CloudStorageError(f"Could not reach OneDrive: {exc}") from exc
