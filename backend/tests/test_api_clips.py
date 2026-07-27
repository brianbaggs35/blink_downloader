"""/api/clips/*: listing+filters, streaming (incl. Range), download, bulk
actions, and analysis (read/reanalyze/bulk-analyze). Reanalyze/bulk-analyze
enqueue against the real test Redis — harmless, nothing consumes the queue
in these tests (same pattern as test_api_blink.py's /blink/sync tests).
"""

# Untyped monkeypatch.setattr(str, lambda) call sites below - same as
# test_integrations_cloud.py.
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownLambdaType=false

import uuid
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.ai.models import AIProviderKind, Analysis, AnalysisTier, SuspicionLabel
from app.biometrics.models import Person, RecognizedFace
from app.blink.models import BlinkAccount, Camera, Clip, StorageBackend
from app.config import get_settings
from app.integrations.cloud import CloudStorageError
from app.security.crypto import SecretBox
from app.settings.service import set_storage_dir


async def _make_camera(app: FastAPI, name: str = "Front Door", enabled: bool = True) -> Camera:
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
            enabled=enabled,
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


async def test_list_filters_by_storage_backend(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    local_clip = await _make_clip(app, camera)
    archived_clip = await _make_clip(app, camera)
    async with app.state.sessionmaker() as session:
        clip = await session.get(Clip, archived_clip.id)
        assert clip is not None
        clip.storage_backend = StorageBackend.S3
        await session.commit()

    response = await admin_client.get("/api/clips", params={"storage_backend": "s3"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(archived_clip.id)

    response = await admin_client.get("/api/clips", params={"storage_backend": "local"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(local_clip.id)


async def _recognize(app: FastAPI, clip: Clip, name: str) -> Person:
    async with app.state.sessionmaker() as session:
        person = Person(name=name)
        session.add(person)
        await session.flush()
        session.add(RecognizedFace(clip_id=clip.id, person_id=person.id, confidence=0.9))
        await session.commit()
        await session.refresh(person)
        return person


async def test_list_includes_recognized_people(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    recognized_clip = await _make_clip(app, camera)
    plain_clip = await _make_clip(app, camera)  # no recognized person
    person = await _recognize(app, recognized_clip, "Alex")

    response = await admin_client.get("/api/clips")
    body = response.json()
    by_id = {item["id"]: item["recognized_people"] for item in body["items"]}
    assert by_id[str(recognized_clip.id)] == [{"id": str(person.id), "name": "Alex"}]
    assert by_id[str(plain_clip.id)] == []


async def test_get_clip_includes_recognized_people(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera)
    person = await _recognize(app, clip, "Sam")

    response = await admin_client.get(f"/api/clips/{clip.id}")
    assert response.json()["recognized_people"] == [{"id": str(person.id), "name": "Sam"}]


async def test_list_filters_by_recognized_person(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    recognized_clip = await _make_clip(app, camera)
    await _make_clip(app, camera)
    person = await _recognize(app, recognized_clip, "Alex")

    response = await admin_client.get("/api/clips", params={"recognized_person_id": str(person.id)})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(recognized_clip.id)


async def test_list_filters_by_has_recognized_person_true(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    recognized_clip = await _make_clip(app, camera)
    await _make_clip(app, camera)
    await _recognize(app, recognized_clip, "Alex")

    response = await admin_client.get("/api/clips", params={"has_recognized_person": "true"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(recognized_clip.id)


async def test_list_filters_by_has_recognized_person_false(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    recognized_clip = await _make_clip(app, camera)
    plain_clip = await _make_clip(app, camera)
    await _recognize(app, recognized_clip, "Alex")

    response = await admin_client.get("/api/clips", params={"has_recognized_person": "false"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(plain_clip.id)


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


# --------------------------------------------------------------- analysis


async def test_get_analysis_404_for_unknown_clip(admin_client: AsyncClient) -> None:
    response = await admin_client.get(f"/api/clips/{uuid.uuid4()}/analysis")
    assert response.status_code == 404


async def test_get_analysis_404_when_not_yet_analyzed(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera)
    response = await admin_client.get(f"/api/clips/{clip.id}/analysis")
    assert response.status_code == 404
    assert "has not been analyzed" in response.json()["detail"]


async def test_get_analysis_returns_the_current_analysis(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera)
    async with app.state.sessionmaker() as session:
        analysis = Analysis(
            clip_id=clip.id,
            summary="A person walks up and leaves a package.",
            suspicion_score=0.2,
            suspicion_label=SuspicionLabel.ROUTINE,
            tier=AnalysisTier.TIER1,
            tier1_provider=AIProviderKind.OPENAI,
            tier1_model="gpt-5-nano",
        )
        session.add(analysis)
        await session.commit()

    response = await admin_client.get(f"/api/clips/{clip.id}/analysis")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "A person walks up and leaves a package."
    assert body["suspicion_label"] == "routine"
    assert body["tier1_model"] == "gpt-5-nano"


# --------------------------------------------------------------- feedback


async def _analyzed_clip(app: FastAPI, camera: Camera, *, suspicion_score: float = 0.8) -> Clip:
    clip = await _make_clip(app, camera)
    async with app.state.sessionmaker() as session:
        analysis = Analysis(
            clip_id=clip.id,
            summary="Someone lingers by the door.",
            suspicion_score=suspicion_score,
            suspicion_label=SuspicionLabel.SUSPICIOUS,
            tier=AnalysisTier.TIER1,
            detected_entities=[
                {"type": "person", "label": "someone", "confidence": 0.9, "bbox": None}
            ],
        )
        session.add(analysis)
        await session.commit()
    return clip


async def test_feedback_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(f"/api/clips/{uuid.uuid4()}/feedback", json={"verdict": "correct"})
    assert response.status_code == 401


async def test_feedback_404_when_not_yet_analyzed(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera)
    response = await admin_client.post(
        f"/api/clips/{clip.id}/feedback", json={"verdict": "correct"}
    )
    assert response.status_code == 404


async def test_feedback_submission_succeeds(
    admin_client: AsyncClient, admin: dict[str, str], app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _analyzed_clip(app, camera)
    response = await admin_client.post(
        f"/api/clips/{clip.id}/feedback",
        json={"verdict": "false_positive", "note": "just a delivery"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] == "false_positive"
    assert body["note"] == "just a delivery"
    assert body["applied"] is True
    assert body["user_id"] == admin["id"]


async def test_feedback_rejects_invalid_verdict(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    clip = await _analyzed_clip(app, camera)
    response = await admin_client.post(
        f"/api/clips/{clip.id}/feedback", json={"verdict": "not-a-real-verdict"}
    )
    assert response.status_code == 422


async def test_list_feedback_returns_all_submissions_newest_first(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _analyzed_clip(app, camera)
    await admin_client.post(f"/api/clips/{clip.id}/feedback", json={"verdict": "correct"})
    await admin_client.post(f"/api/clips/{clip.id}/feedback", json={"verdict": "false_positive"})

    response = await admin_client.get(f"/api/clips/{clip.id}/feedback")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["verdict"] == "false_positive"  # most recent first


async def test_viewer_can_submit_and_list_feedback(
    viewer_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _analyzed_clip(app, camera)
    response = await viewer_client.post(
        f"/api/clips/{clip.id}/feedback", json={"verdict": "correct"}
    )
    assert response.status_code == 201
    assert (await viewer_client.get(f"/api/clips/{clip.id}/feedback")).status_code == 200


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
    arcname1 = f"Front Door/2026-07-20/{clip1.filename}"
    arcname2 = f"Front Door/2026-07-20/{clip2.filename}"
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        names = sorted(zf.namelist())
        assert names == sorted([arcname1, arcname2])
        assert zf.read(arcname1) == b"clip-one"
        assert zf.read(arcname2) == b"clip-two"


async def test_bulk_download_organizes_by_camera_and_date(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    driveway = await _make_camera(app, "Driveway")
    backyard = await _make_camera(app, "Backyard")
    clip1 = await _make_clip(
        app,
        driveway,
        downloaded=True,
        storage_dir=tmp_path,
        recorded_at=datetime(2026, 1, 5, tzinfo=UTC),
    )
    clip2 = await _make_clip(
        app,
        backyard,
        downloaded=True,
        storage_dir=tmp_path,
        recorded_at=datetime(2026, 1, 6, tzinfo=UTC),
    )

    response = await admin_client.post(
        "/api/clips/bulk-download", json={"clip_ids": [str(clip1.id), str(clip2.id)]}
    )
    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        names = set(zf.namelist())
        assert names == {
            f"Driveway/2026-01-05/{clip1.filename}",
            f"Backyard/2026-01-06/{clip2.filename}",
        }


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
    assert present.filename is not None
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        assert zf.namelist() == [f"Front Door/2026-07-20/{present.filename}"]


async def test_bulk_download_includes_a_cloud_archived_clip(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    local_clip = await _make_clip(
        app, camera, downloaded=True, storage_dir=tmp_path, content=b"local-bytes"
    )
    async with app.state.sessionmaker() as session:
        archived_clip = Clip(
            camera_id=camera.id,
            blink_clip_id="/media/archived.mp4",
            recorded_at=datetime(2026, 7, 21, tzinfo=UTC),
            raw_metadata={},
            storage_backend=StorageBackend.S3,
            storage_path="clips/archived.mp4",
            filename="archived.mp4",
            downloaded_at=datetime.now(UTC),
        )
        session.add(archived_clip)
        await session.commit()
        await session.refresh(archived_clip)

    class _FakeS3:
        async def download(self, key: str) -> bytes:
            assert key == "clips/archived.mp4"
            return b"cloud-bytes"

    monkeypatch.setattr("app.api.clips.build_s3_client", lambda *_a, **_kw: _FakeS3())
    response = await admin_client.post(
        "/api/clips/bulk-download",
        json={"clip_ids": [str(local_clip.id), str(archived_clip.id)]},
    )
    assert response.status_code == 200
    assert local_clip.filename is not None
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        names = set(zf.namelist())
        assert names == {
            f"Front Door/2026-07-20/{local_clip.filename}",
            "Front Door/2026-07-21/archived.mp4",
        }
        assert zf.read("Front Door/2026-07-21/archived.mp4") == b"cloud-bytes"


async def test_bulk_download_reuses_one_client_for_two_clips_on_the_same_backend(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    async with app.state.sessionmaker() as session:
        clip_a = Clip(
            camera_id=camera.id,
            blink_clip_id="/media/a.mp4",
            recorded_at=datetime(2026, 7, 21, tzinfo=UTC),
            raw_metadata={},
            storage_backend=StorageBackend.GOOGLE_DRIVE,
            storage_path="file-a",
            filename="a.mp4",
            downloaded_at=datetime.now(UTC),
        )
        clip_b = Clip(
            camera_id=camera.id,
            blink_clip_id="/media/b.mp4",
            recorded_at=datetime(2026, 7, 22, tzinfo=UTC),
            raw_metadata={},
            storage_backend=StorageBackend.GOOGLE_DRIVE,
            storage_path="file-b",
            filename="b.mp4",
            downloaded_at=datetime.now(UTC),
        )
        session.add_all([clip_a, clip_b])
        await session.commit()

    build_calls = 0

    class _FakeDrive:
        async def download(self, file_id: str) -> bytes:
            return f"bytes-for-{file_id}".encode()

    def _build(*_a: object, **_kw: object) -> _FakeDrive:
        nonlocal build_calls
        build_calls += 1
        return _FakeDrive()

    monkeypatch.setattr("app.api.clips.build_google_drive_client", _build)
    response = await admin_client.post(
        "/api/clips/bulk-download", json={"clip_ids": [str(clip_a.id), str(clip_b.id)]}
    )
    assert response.status_code == 200
    assert build_calls == 1
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        assert zf.read("Front Door/2026-07-21/a.mp4") == b"bytes-for-file-a"
        assert zf.read("Front Door/2026-07-22/b.mp4") == b"bytes-for-file-b"


async def test_bulk_download_includes_a_onedrive_archived_clip(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    async with app.state.sessionmaker() as session:
        archived_clip = Clip(
            camera_id=camera.id,
            blink_clip_id="/media/archived.mp4",
            recorded_at=datetime(2026, 7, 21, tzinfo=UTC),
            raw_metadata={},
            storage_backend=StorageBackend.ONEDRIVE,
            storage_path="item-1",
            filename="archived.mp4",
            downloaded_at=datetime.now(UTC),
        )
        session.add(archived_clip)
        await session.commit()

    class _FakeOneDrive:
        async def download(self, item_id: str) -> bytes:
            assert item_id == "item-1"
            return b"onedrive-bytes"

    monkeypatch.setattr("app.api.clips.build_onedrive_client", lambda *_a, **_kw: _FakeOneDrive())
    response = await admin_client.post(
        "/api/clips/bulk-download", json={"clip_ids": [str(archived_clip.id)]}
    )
    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        assert zf.read("Front Door/2026-07-21/archived.mp4") == b"onedrive-bytes"


async def test_bulk_download_skips_a_cloud_clip_whose_backend_is_unconfigured(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    async with app.state.sessionmaker() as session:
        archived_clip = Clip(
            camera_id=camera.id,
            blink_clip_id="/media/archived.mp4",
            recorded_at=datetime(2026, 7, 21, tzinfo=UTC),
            raw_metadata={},
            storage_backend=StorageBackend.S3,
            storage_path="clips/archived.mp4",
            filename="archived.mp4",
            downloaded_at=datetime.now(UTC),
        )
        session.add(archived_clip)
        await session.commit()

    response = await admin_client.post(
        "/api/clips/bulk-download", json={"clip_ids": [str(archived_clip.id)]}
    )
    assert response.status_code == 404


async def test_bulk_download_skips_a_cloud_clip_that_fails_to_fetch(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    async with app.state.sessionmaker() as session:
        archived_clip = Clip(
            camera_id=camera.id,
            blink_clip_id="/media/archived.mp4",
            recorded_at=datetime(2026, 7, 21, tzinfo=UTC),
            raw_metadata={},
            storage_backend=StorageBackend.S3,
            storage_path="clips/archived.mp4",
            filename="archived.mp4",
            downloaded_at=datetime.now(UTC),
        )
        session.add(archived_clip)
        await session.commit()

    class _RaisingS3:
        async def download(self, key: str) -> bytes:
            raise CloudStorageError("boom")

    monkeypatch.setattr("app.api.clips.build_s3_client", lambda *_a, **_kw: _RaisingS3())
    response = await admin_client.post(
        "/api/clips/bulk-download", json={"clip_ids": [str(archived_clip.id)]}
    )
    assert response.status_code == 404


async def test_bulk_download_404_when_none_downloaded(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera)
    response = await admin_client.post(
        "/api/clips/bulk-download", json={"clip_ids": [str(clip.id)]}
    )
    assert response.status_code == 404


# -------------------------------------------------------------- reanalyze


async def test_reanalyze_requires_downloaded_clip(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera)  # not downloaded
    response = await admin_client.post(f"/api/clips/{clip.id}/reanalyze")
    assert response.status_code == 400


async def test_reanalyze_unknown_clip_is_404(admin_client: AsyncClient) -> None:
    response = await admin_client.post(f"/api/clips/{uuid.uuid4()}/reanalyze")
    assert response.status_code == 404


async def test_reanalyze_enqueues_a_job(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)
    response = await admin_client.post(f"/api/clips/{clip.id}/reanalyze")
    assert response.status_code == 202
    assert response.json() == {"status": "queued"}


async def test_reanalyze_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(f"/api/clips/{uuid.uuid4()}/reanalyze")
    assert response.status_code == 401


async def test_reanalyze_rejected_when_camera_disabled(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app, enabled=False)
    clip = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)
    response = await admin_client.post(f"/api/clips/{clip.id}/reanalyze")
    assert response.status_code == 409


# ------------------------------------------------------------ bulk-analyze


async def test_bulk_analyze_queues_downloaded_and_reports_the_rest(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    downloaded = await _make_clip(app, camera, downloaded=True, storage_dir=tmp_path)
    not_downloaded = await _make_clip(app, camera)
    missing_id = uuid.uuid4()

    response = await admin_client.post(
        "/api/clips/bulk-analyze",
        json={"clip_ids": [str(downloaded.id), str(not_downloaded.id), str(missing_id)]},
    )
    assert response.status_code == 200
    assert response.json() == {"succeeded": 1, "failed": 2}


async def test_bulk_analyze_empty_list_rejected(admin_client: AsyncClient) -> None:
    response = await admin_client.post("/api/clips/bulk-analyze", json={"clip_ids": []})
    assert response.status_code == 422


async def test_bulk_analyze_excludes_disabled_camera_clips(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    enabled_camera = await _make_camera(app, name="Front Door")
    disabled_camera = await _make_camera(app, name="Backyard", enabled=False)
    from_enabled = await _make_clip(app, enabled_camera, downloaded=True, storage_dir=tmp_path)
    from_disabled = await _make_clip(app, disabled_camera, downloaded=True, storage_dir=tmp_path)

    response = await admin_client.post(
        "/api/clips/bulk-analyze",
        json={"clip_ids": [str(from_enabled.id), str(from_disabled.id)]},
    )
    assert response.status_code == 200
    assert response.json() == {"succeeded": 1, "failed": 1}


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
    assert (await viewer_client.post(f"/api/clips/{clip.id}/reanalyze")).status_code == 403
    assert (
        await viewer_client.post("/api/clips/bulk-analyze", json={"clip_ids": [str(clip.id)]})
    ).status_code == 403
    assert (
        await viewer_client.post("/api/clips/bulk-download", json={"clip_ids": [str(clip.id)]})
    ).status_code == 403
