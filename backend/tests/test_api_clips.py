"""/api/clips/*: listing+filters, streaming (incl. Range), download, bulk actions."""

import uuid
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.blink.models import BlinkAccount, Camera, Clip
from app.config import get_settings
from app.security.crypto import SecretBox
from app.settings.service import set_storage_dir


async def _make_camera(app: FastAPI, name: str = "Front Door") -> Camera:
    async with app.state.sessionmaker() as session:
        box = SecretBox(get_settings().encryption_key)
        account = BlinkAccount(
            encrypted_username=box.encrypt("u"),
            encrypted_password=box.encrypt("p"),
            encrypted_token_data=box.encrypt("{}"),
        )
        session.add(account)
        await session.flush()
        camera = Camera(
            blink_account_id=account.id,
            blink_camera_id=f"cam-{name}",
            blink_network_id="net-1",
            name=name,
            camera_type="catalina",
        )
        session.add(camera)
        await session.commit()
        await session.refresh(camera)
        return camera


async def _make_clip(
    app: FastAPI,
    camera: Camera,
    *,
    recorded_at: datetime | None = None,
    blink_clip_id: str | None = None,
    downloaded: bool = False,
    storage_dir: Path | None = None,
    content: bytes = b"fake-video-bytes",
) -> Clip:
    async with app.state.sessionmaker() as session:
        clip = Clip(
            camera_id=camera.id,
            blink_clip_id=blink_clip_id or f"/media/{uuid.uuid4()}.mp4",
            recorded_at=recorded_at or datetime(2026, 7, 20, tzinfo=UTC),
            raw_metadata={},
        )
        session.add(clip)
        await session.commit()
        await session.refresh(clip)

        if downloaded:
            assert storage_dir is not None
            path = storage_dir / str(camera.id) / f"{clip.id}.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            clip.storage_path = str(path)
            clip.filename = path.name
            clip.file_size_bytes = len(content)
            clip.downloaded_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(clip)
        return clip


async def _use_storage(app: FastAPI, tmp_path: Path) -> None:
    async with app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))


# --------------------------------------------------------------------- list


async def test_list_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/clips")
    assert response.status_code == 401


async def test_list_is_empty_with_no_clips(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/clips")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 24}


async def test_list_filters_by_camera(admin_client: AsyncClient, app: FastAPI) -> None:
    cam_a = await _make_camera(app, "A")
    cam_b = await _make_camera(app, "B")
    await _make_clip(app, cam_a)
    await _make_clip(app, cam_b)

    response = await admin_client.get("/api/clips", params={"camera_id": str(cam_a.id)})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["camera_id"] == str(cam_a.id)


async def test_list_filters_by_date_range(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    await _make_clip(app, camera, recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    await _make_clip(app, camera, recorded_at=datetime(2026, 6, 1, tzinfo=UTC))

    response = await admin_client.get(
        "/api/clips",
        params={"since": "2026-05-01T00:00:00Z", "until": "2026-07-01T00:00:00Z"},
    )
    body = response.json()
    assert body["total"] == 1


async def test_list_filters_downloaded_only(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    await _make_clip(app, camera, downloaded=False)
    await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)

    response = await admin_client.get("/api/clips", params={"downloaded_only": True})
    body = response.json()
    assert body["total"] == 1


async def test_list_orders_newest_first_and_paginates(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    await _make_clip(app, camera, recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    await _make_clip(app, camera, recorded_at=datetime(2026, 6, 1, tzinfo=UTC))
    await _make_clip(app, camera, recorded_at=datetime(2026, 3, 1, tzinfo=UTC))

    response = await admin_client.get("/api/clips", params={"page": 1, "page_size": 2})
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    months = [item["recorded_at"][5:7] for item in body["items"]]
    assert months == ["06", "03"]

    page2 = await admin_client.get("/api/clips", params={"page": 2, "page_size": 2})
    assert len(page2.json()["items"]) == 1


async def test_page_size_over_max_is_rejected(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/clips", params={"page_size": 1000})
    assert response.status_code == 422


# ---------------------------------------------------------------------- get


async def test_get_unknown_clip_is_404(admin_client: AsyncClient) -> None:
    response = await admin_client.get(f"/api/clips/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_returns_clip_metadata(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera)
    response = await admin_client.get(f"/api/clips/{clip.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(clip.id)


# ------------------------------------------------------------------- stream


async def test_stream_404_when_not_downloaded(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera)
    response = await admin_client.get(f"/api/clips/{clip.id}/stream")
    assert response.status_code == 404


async def test_stream_returns_full_file_inline(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path, content=b"x" * 1000)

    response = await admin_client.get(f"/api/clips/{clip.id}/stream")
    assert response.status_code == 200
    assert response.content == b"x" * 1000
    assert "attachment" not in response.headers.get("content-disposition", "")


async def test_stream_supports_range_requests(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    content = bytes(range(256)) * 4  # 1024 bytes, byte-addressable content
    clip = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path, content=content)

    response = await admin_client.get(
        f"/api/clips/{clip.id}/stream", headers={"Range": "bytes=100-199"}
    )
    assert response.status_code == 206
    assert response.content == content[100:200]
    assert response.headers["content-range"] == f"bytes 100-199/{len(content)}"


async def test_stream_404_when_file_missing_from_disk(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)
    Path(clip.storage_path).unlink()  # type: ignore[arg-type]

    response = await admin_client.get(f"/api/clips/{clip.id}/stream")
    assert response.status_code == 404


# ---------------------------------------------------------------- thumbnail


async def test_thumbnail_404_when_not_generated(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera)
    response = await admin_client.get(f"/api/clips/{clip.id}/thumbnail")
    assert response.status_code == 404


async def test_thumbnail_returns_the_image(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)
    thumb_path = tmp_path / str(camera.id) / f"{clip.id}.jpg"
    thumb_path.write_bytes(b"\xff\xd8fake-jpeg")
    async with app.state.sessionmaker() as session:
        from sqlalchemy import select

        row = (await session.execute(select(Clip).where(Clip.id == clip.id))).scalar_one()
        row.thumbnail_generated = True
        await session.commit()

    response = await admin_client.get(f"/api/clips/{clip.id}/thumbnail")
    assert response.status_code == 200
    assert response.content == b"\xff\xd8fake-jpeg"


# ----------------------------------------------------------------- download


async def test_download_forces_attachment(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)
    response = await admin_client.get(f"/api/clips/{clip.id}/download")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert clip.filename is not None
    assert clip.filename in response.headers["content-disposition"]


# ------------------------------------------------------------------ delete


async def test_delete_removes_row_and_file(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)
    path = Path(clip.storage_path)  # type: ignore[arg-type]

    response = await admin_client.delete(f"/api/clips/{clip.id}")
    assert response.status_code == 204
    assert not path.exists()

    followup = await admin_client.get(f"/api/clips/{clip.id}")
    assert followup.status_code == 404


async def test_delete_storage_failure_is_502(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)

    from app.storage.service import StorageError

    async def fail_delete(*_args: object, **_kwargs: object) -> None:
        raise StorageError("permission denied")

    monkeypatch.setattr("app.storage.service.LocalClipStorage.delete", fail_delete)
    response = await admin_client.delete(f"/api/clips/{clip.id}")
    assert response.status_code == 502

    # The row must still exist — the failed delete rolled back.
    followup = await admin_client.get(f"/api/clips/{clip.id}")
    assert followup.status_code == 200


async def test_delete_unknown_clip_is_404(admin_client: AsyncClient) -> None:
    response = await admin_client.delete(f"/api/clips/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_delete_requires_authentication(client: AsyncClient) -> None:
    response = await client.delete(f"/api/clips/{uuid.uuid4()}")
    assert response.status_code == 401


# ------------------------------------------------------------- bulk actions


async def test_bulk_delete_reports_succeeded_and_failed(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip1 = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)
    clip2 = await _make_clip(app, camera)
    missing_id = uuid.uuid4()

    response = await admin_client.post(
        "/api/clips/bulk-delete",
        json={"clip_ids": [str(clip1.id), str(clip2.id), str(missing_id)]},
    )
    assert response.status_code == 200
    assert response.json() == {"succeeded": 2, "failed": 1}


async def test_bulk_delete_partial_storage_failure_still_reports_the_rest(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip1 = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)
    clip2 = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)

    from app.storage.service import StorageError

    call_count = 0

    async def fail_second_delete(self: object, path: Path) -> None:
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise StorageError("permission denied")

    monkeypatch.setattr("app.storage.service.LocalClipStorage.delete", fail_second_delete)
    response = await admin_client.post(
        "/api/clips/bulk-delete", json={"clip_ids": [str(clip1.id), str(clip2.id)]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] + body["failed"] == 2
    assert body["failed"] >= 1


async def test_bulk_delete_empty_list_rejected(admin_client: AsyncClient) -> None:
    response = await admin_client.post("/api/clips/bulk-delete", json={"clip_ids": []})
    assert response.status_code == 422


async def test_bulk_download_builds_a_real_zip(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip1 = await _make_clip(
        app, camera, downloaded=True, storage_dir=tmp_path, content=b"clip-one"
    )
    clip2 = await _make_clip(
        app, camera, downloaded=True, storage_dir=tmp_path, content=b"clip-two"
    )
    not_downloaded = await _make_clip(app, camera)

    response = await admin_client.post(
        "/api/clips/bulk-download",
        json={"clip_ids": [str(clip1.id), str(clip2.id), str(not_downloaded.id)]},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]

    assert clip1.filename is not None
    assert clip2.filename is not None
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        names = sorted(zf.namelist())
        assert names == sorted([clip1.filename, clip2.filename])
        assert zf.read(clip1.filename) == b"clip-one"
        assert zf.read(clip2.filename) == b"clip-two"


async def test_bulk_download_skips_a_file_missing_from_disk(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    present = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path, content=b"ok")
    ghost = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path, content=b"gone")
    Path(ghost.storage_path).unlink()  # type: ignore[arg-type]

    response = await admin_client.post(
        "/api/clips/bulk-download", json={"clip_ids": [str(present.id), str(ghost.id)]}
    )
    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        assert zf.namelist() == [present.filename]


async def test_bulk_download_404_when_none_downloaded(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera)
    response = await admin_client.post(
        "/api/clips/bulk-download", json={"clip_ids": [str(clip.id)]}
    )
    assert response.status_code == 404


# ------------------------------------------------------- viewer is read-only


async def test_viewer_can_list_get_and_stream(
    viewer_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)

    assert (await viewer_client.get("/api/clips")).status_code == 200
    assert (await viewer_client.get(f"/api/clips/{clip.id}")).status_code == 200
    assert (await viewer_client.get(f"/api/clips/{clip.id}/stream")).status_code == 200


async def test_viewer_cannot_download_delete_or_bulk_act(
    viewer_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)

    assert (await viewer_client.get(f"/api/clips/{clip.id}/download")).status_code == 403
    assert (await viewer_client.delete(f"/api/clips/{clip.id}")).status_code == 403
    assert (
        await viewer_client.post("/api/clips/bulk-delete", json={"clip_ids": [str(clip.id)]})
    ).status_code == 403
    assert (
        await viewer_client.post("/api/clips/bulk-download", json={"clip_ids": [str(clip.id)]})
    ).status_code == 403
