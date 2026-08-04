"""Seed deterministic fixtures for the e2e stack.

Run inside the e2e backend container after migrations:
``python -m app.testing.seed``

Idempotent: an already-seeded database is left untouched. Fixtures are
intentionally synthetic (a generated test-pattern clip, not a real Blink
recording) — they exist so Playwright tests have known clips, an AI
analysis, and a recognized person to assert against without needing a real
Blink account or a real camera.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi_users.password import PasswordHelper
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIProviderKind, AIUsage, Analysis, AnalysisTier, SuspicionLabel
from app.biometrics.models import FaceEmbedding, Person, RecognizedFace
from app.biometrics.service import download_biometrics_model, get_biometrics_settings
from app.blink.models import BlinkAccount, Camera, Clip
from app.config import get_settings
from app.db import build_engine, build_sessionmaker
from app.logs import configure_logging, get_logger
from app.security.crypto import SecretBox
from app.settings.service import resolve_storage_dir
from app.storage.service import ClipStorage, get_clip_storage
from app.sync_module.models import (
    LocalItemStatus,
    LocalStorageStatus,
    SyncModule,
    SyncModuleLocalItem,
)
from app.users.models import User
from app.vehicles.models import ProximityEvent, Vehicle

logger = get_logger(__name__)

E2E_ADMIN_EMAIL = os.environ.get("BLINK_E2E_ADMIN_EMAIL", "e2e-admin@example.com")
E2E_ADMIN_PASSWORD = os.environ.get("BLINK_E2E_ADMIN_PASSWORD", "e2e-admin-password-123")

DEMO_PERSON_NAME = "Alex Demo"


async def _make_demo_clip_bytes() -> bytes:
    """A tiny, deterministic, synthetic MP4 - real enough for ffmpeg's own
    probing/thumbnailing/playback to work on, without needing a real Blink
    recording checked into the repo or downloaded at seed time."""
    # /tmp usage is intentional here, not a vulnerability: this is e2e/dev
    # seed-only code (never runs in production), the filename is
    # UUID-randomized (defeats the predictable-path/symlink attack this rule
    # class warns about), and the file is used and removed within this same
    # function.
    path = f"/tmp/blink-e2e-seed-{uuid.uuid4()}.mp4"  # noqa: S108 # nosec B108 # NOSONAR
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=3:size=320x240:rate=10",
        "-pix_fmt",
        "yuv420p",
        path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    try:
        return await asyncio.to_thread(Path(path).read_bytes)
    finally:
        await asyncio.to_thread(os.remove, path)


async def _make_demo_preview_bytes(seed: int) -> bytes:
    """A tiny, deterministic, synthetic JPEG - stands in for a camera's
    latest snapshot so Live View and Security Feed have something real to
    render without a live Blink connection. `seed` varies the pattern so
    different cameras' tiles are visibly distinct in a screenshot."""
    # See _make_demo_clip_bytes' identical comment above - same reasoning.
    path = f"/tmp/blink-e2e-preview-{uuid.uuid4()}.jpg"  # noqa: S108 # nosec B108 # NOSONAR
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=640x360:rate=1,format=yuvj420p",
        "-vf",
        f"hue=h={seed * 45}",
        "-vframes",
        "1",
        path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    try:
        return await asyncio.to_thread(Path(path).read_bytes)
    finally:
        await asyncio.to_thread(os.remove, path)


async def _seed_demo_data(session: AsyncSession) -> None:
    settings = get_settings()
    box = SecretBox(settings.encryption_key)
    # Same DB-configurable-with-a-default resolution every other storage
    # consumer uses (app/api/biometrics.py, app/worker/tasks/download.py,
    # ...) - not the hardcoded config default directly, which would try
    # (and fail) to write under /data/clips outside a container that
    # actually mounts it there, e.g. a bare `pytest`/CI run.
    storage = get_clip_storage(await resolve_storage_dir(session, settings))
    clip_bytes = await _make_demo_clip_bytes()

    account = BlinkAccount(
        encrypted_username=box.encrypt("demo@example.com"),
        encrypted_password=box.encrypt("not-a-real-password"),
        encrypted_token_data=box.encrypt("{}"),
        last_sync=datetime.now(UTC),
    )
    session.add(account)
    await session.flush()

    front_door = Camera(
        blink_account_id=account.id,
        blink_camera_id="demo-front-door",
        blink_network_id="demo-network",
        name="Front Door",
        camera_type="catalina",
        security_context="Watches the front porch and driveway.",
    )
    backyard = Camera(
        blink_account_id=account.id,
        blink_camera_id="demo-backyard",
        blink_network_id="demo-network",
        name="Backyard",
        camera_type="catalina",
    )
    session.add_all([front_door, backyard])
    await session.flush()

    now = datetime.now(UTC)

    # A cached preview per camera - without one, Live View and Security Feed
    # have no live Blink connection to fall back on and every tile would 404.
    for index, camera in enumerate([front_door, backyard]):
        preview_bytes = await _make_demo_preview_bytes(index)
        preview_path = storage.camera_preview_path(camera.id)
        await storage.write(preview_path, preview_bytes)
        camera.preview_path = str(preview_path)
        camera.preview_updated_at = now

    # Spread across the Biometrics tab's enrollment time-range options
    # (24h/48h/7d) so seeded data can actually exercise all three, plus one
    # clip older than any of them and one not-yet-downloaded. The disposable
    # batch at the end is deliberately the newest of the whole set and has no
    # analysis/vehicle/face relations pointing at any of it - e2e's own
    # delete/bulk-delete tests need something disposable to remove that
    # nothing else in the fixture set depends on, and "newest first" (the
    # Library's default sort) makes them reliably selectable via
    # .first()/.nth(1)/etc. without a search/filter step. There are ten of
    # them, not two: Playwright's own retries (playwright.config.ts,
    # retries: 2 under CI) mean a single flaky delete test can consume more
    # than one disposable clip per run (each retry re-selects "whatever is
    # currently first/second" and deletes it again), and fullyParallel means
    # more than one delete-ish test can be doing this at once - a too-small
    # buffer here doesn't fail loudly, it silently cascades into deleting
    # real fixture clips (and anything that references them) once exhausted.
    clip_specs = [
        (front_door, now - timedelta(hours=2), True),
        (front_door, now - timedelta(hours=30), True),
        (front_door, now - timedelta(days=5), True),
        (backyard, now - timedelta(hours=6), True),
        (backyard, now - timedelta(days=10), True),
        (backyard, now - timedelta(minutes=21), False),  # still "downloading"
        *[
            (front_door, now - timedelta(minutes=minutes), True)  # disposable
            for minutes in range(2, 22, 2)
        ],
    ]

    clips: list[Clip] = []
    for camera, recorded_at, downloaded in clip_specs:
        clip = Clip(
            camera_id=camera.id,
            blink_clip_id=f"/media/demo/{uuid.uuid4()}.mp4",
            recorded_at=recorded_at,
        )
        session.add(clip)
        await session.flush()
        if downloaded:
            path = storage.clip_path(camera.id, clip.id, recorded_at)
            await storage.write(path, clip_bytes)
            clip.storage_path = str(path)
            clip.downloaded_at = recorded_at + timedelta(seconds=30)
            clip.file_size_bytes = len(clip_bytes)
            clip.duration_seconds = 3.0
        clips.append(clip)
    await session.flush()

    # A routine analysis on one clip, a suspicious one (with a person entity
    # later recognized) on another - enough for the Library/AI tab/clip
    # modal to all have something real to show.
    routine = Analysis(
        clip_id=clips[2].id,
        summary="A package is dropped off at the front door; nothing unusual.",
        suspicion_score=0.15,
        suspicion_label=SuspicionLabel.ROUTINE,
        tier=AnalysisTier.TIER1,
        detected_entities=[
            {
                "type": "package",
                "label": "a package",
                "confidence": 0.88,
                "bbox": [0.4, 0.5, 0.2, 0.2],
                "recognized_person_id": None,
            }
        ],
    )
    suspicious_entity_bbox = [0.3, 0.2, 0.25, 0.6]
    suspicious = Analysis(
        clip_id=clips[0].id,
        summary="A person lingers by the front door for an extended period after dark.",
        suspicion_score=0.78,
        suspicion_label=SuspicionLabel.SUSPICIOUS,
        tier=AnalysisTier.TIER2,
        escalated=True,
        detected_entities=[
            {
                "type": "person",
                "label": DEMO_PERSON_NAME,
                "confidence": 0.93,
                "bbox": suspicious_entity_bbox,
                "recognized_person_id": None,  # backfilled below once the person exists
            }
        ],
    )
    session.add_all([routine, suspicious])
    await session.flush()

    # One enrolled person with a face sample and a recognized appearance on
    # the "suspicious" clip above, so the recognized-badge/filter/clip-modal
    # name-override all have something real to display without needing a
    # live insightface model download during seeding.
    person = Person(name=DEMO_PERSON_NAME)
    session.add(person)
    await session.flush()

    embedding_id = uuid.uuid4()
    fake_embedding = [0.0] * 512
    fake_embedding[0] = 1.0
    sample_path = storage.face_sample_path(person.id, embedding_id)
    await storage.write(sample_path, clip_bytes[:64])  # placeholder image bytes
    session.add(
        FaceEmbedding(
            id=embedding_id,
            person_id=person.id,
            embedding=fake_embedding,
            source_clip_id=clips[0].id,
            source_frame_seconds=1.0,
            thumbnail_path=str(sample_path),
        )
    )
    profile_path = storage.person_thumbnail_path(person.id)
    await storage.write(profile_path, clip_bytes[:64])
    person.thumbnail_path = str(profile_path)

    session.add(RecognizedFace(clip_id=clips[0].id, person_id=person.id, confidence=0.93))
    suspicious.detected_entities = [
        {**suspicious.detected_entities[0], "recognized_person_id": str(person.id)}
    ]

    await _seed_vehicle_data(session, storage, front_door, clips)
    _seed_ai_usage_data(session, clips, routine, suspicious)
    await _seed_sync_module_data(session, storage, account, front_door, backyard, clip_bytes)


async def _seed_vehicle_data(
    session: AsyncSession, storage: ClipStorage, camera: Camera, clips: list[Clip]
) -> None:
    """One protected vehicle on the front door camera, with a few recent
    proximity events - enough for the Vehicles tab's card, outline overlay,
    and recent-activity list to all have something real to show."""
    reference_bytes = await _make_demo_preview_bytes(2)
    reference_path = storage.vehicle_reference_path(camera.id)
    await storage.write(reference_path, reference_bytes)

    vehicle = Vehicle(
        camera_id=camera.id,
        description="A silver sedan is normally parked in the driveway overnight.",
        outline_points=[[0.3, 0.55], [0.7, 0.55], [0.75, 0.85], [0.25, 0.85]],
        reference_frame_path=str(reference_path),
        estimated_length_feet=16.0,
        distance_threshold_feet=10.0,
    )
    session.add(vehicle)
    await session.flush()

    now = datetime.now(UTC)
    session.add_all(
        [
            ProximityEvent(
                vehicle_id=vehicle.id,
                clip_id=clips[0].id,
                distance_feet=4.2,
                error_margin_feet=1.1,
                occurred_at=now - timedelta(hours=2),
            ),
            ProximityEvent(
                vehicle_id=vehicle.id,
                clip_id=clips[1].id,
                distance_feet=7.8,
                error_margin_feet=1.4,
                occurred_at=now - timedelta(hours=30),
            ),
            ProximityEvent(
                vehicle_id=vehicle.id,
                clip_id=clips[2].id,
                distance_feet=2.5,
                error_margin_feet=0.9,
                occurred_at=now - timedelta(days=5),
            ),
        ]
    )


async def _seed_sync_module_data(
    session: AsyncSession,
    storage: ClipStorage,
    account: BlinkAccount,
    front_door: Camera,
    backyard: Camera,
    clip_bytes: bytes,
) -> None:
    """One physical Sync Module on the same seeded network (armed, online,
    local storage compatible/enabled/active), with local (USB) storage
    items spanning AVAILABLE/DOWNLOADED/ERROR - enough for the Sync Module
    tab's arm control, motion toggles, and file browser to all have
    something real to show."""
    now = datetime.now(UTC)
    sync_module = SyncModule(
        blink_account_id=account.id,
        network_id="demo-network",
        sync_id="demo-sync-1",
        name="Home",
        serial="SN-DEMO-0001",
        firmware_version="2.14.28",
        is_physical_hub=True,
        armed=True,
        online=True,
        local_storage_compatible=True,
        local_storage_enabled=True,
        local_storage_active=True,
        local_storage_manifest_id="demo-manifest-1",
        local_storage_status=LocalStorageStatus.IDLE,
        local_storage_manifest_refreshed_at=now - timedelta(minutes=30),
        last_synced_at=now,
    )
    session.add(sync_module)
    await session.flush()

    session.add(
        SyncModuleLocalItem(
            sync_module_id=sync_module.id,
            camera_id=front_door.id,
            camera_name=front_door.name,
            blink_item_id=1,
            recorded_at=now - timedelta(hours=1),
            size_bytes=52_428_800,
        )
    )

    downloaded_recorded_at = now - timedelta(hours=4)
    downloaded = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_id=backyard.id,
        camera_name=backyard.name,
        blink_item_id=2,
        recorded_at=downloaded_recorded_at,
        size_bytes=len(clip_bytes),
        status=LocalItemStatus.DOWNLOADED,
        downloaded_at=downloaded_recorded_at + timedelta(seconds=45),
    )
    session.add(downloaded)
    await session.flush()
    downloaded_path = storage.sync_module_clip_path(
        sync_module.id, downloaded.id, downloaded_recorded_at
    )
    await storage.write(downloaded_path, clip_bytes)
    downloaded.storage_path = str(downloaded_path)

    session.add(
        SyncModuleLocalItem(
            sync_module_id=sync_module.id,
            camera_id=front_door.id,
            camera_name=front_door.name,
            blink_item_id=3,
            recorded_at=now - timedelta(hours=8),
            size_bytes=41_943_040,
            status=LocalItemStatus.ERROR,
            last_error="Failed to prepare this clip from the Sync Module - device busy.",
        )
    )


def _seed_ai_usage_data(
    session: AsyncSession, clips: list[Clip], routine: Analysis, suspicious: Analysis
) -> None:
    """Usage rows spread across the last week, across more than one
    provider/model and including one failure - enough for the AI Usage
    tab's KPI tiles, daily chart, and by-provider breakdown to all have
    something real (and non-trivial) to show."""
    now = datetime.now(UTC)
    session.add_all(
        [
            AIUsage(
                analysis_id=routine.id,
                clip_id=routine.clip_id,
                tier=AnalysisTier.TIER1,
                provider=AIProviderKind.ANTHROPIC,
                model="claude-haiku-4-5",
                prompt_tokens=1200,
                completion_tokens=180,
                total_tokens=1380,
                frame_count=4,
                estimated_cost_usd=0.008,
                latency_ms=1450,
                success=True,
                created_at=now - timedelta(days=6, hours=1),
            ),
            AIUsage(
                analysis_id=suspicious.id,
                clip_id=suspicious.clip_id,
                tier=AnalysisTier.TIER1,
                provider=AIProviderKind.ANTHROPIC,
                model="claude-haiku-4-5",
                prompt_tokens=1350,
                completion_tokens=210,
                total_tokens=1560,
                frame_count=4,
                estimated_cost_usd=0.009,
                latency_ms=1610,
                success=True,
                created_at=now - timedelta(days=4, hours=3),
            ),
            AIUsage(
                analysis_id=suspicious.id,
                clip_id=suspicious.clip_id,
                tier=AnalysisTier.TIER2,
                provider=AIProviderKind.OPENAI,
                model="gpt-5-mini",
                prompt_tokens=2100,
                completion_tokens=340,
                total_tokens=2440,
                frame_count=8,
                estimated_cost_usd=0.041,
                latency_ms=2870,
                success=True,
                created_at=now - timedelta(days=4, hours=3, minutes=1),
            ),
            AIUsage(
                clip_id=clips[3].id,
                tier=AnalysisTier.TIER1,
                provider=AIProviderKind.ANTHROPIC,
                model="claude-haiku-4-5",
                prompt_tokens=1180,
                completion_tokens=160,
                total_tokens=1340,
                frame_count=4,
                estimated_cost_usd=0.007,
                latency_ms=1390,
                success=True,
                created_at=now - timedelta(days=2, hours=5),
            ),
            AIUsage(
                clip_id=clips[3].id,
                tier=AnalysisTier.TIER1,
                provider=AIProviderKind.OPENAI,
                model="gpt-5-mini",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                frame_count=4,
                estimated_cost_usd=0,
                latency_ms=640,
                success=False,
                error_message="The provider's API returned a 503 while analyzing this clip.",
                created_at=now - timedelta(days=1, hours=2),
            ),
            AIUsage(
                clip_id=clips[0].id,
                tier=AnalysisTier.TIER1,
                provider=AIProviderKind.ANTHROPIC,
                model="claude-haiku-4-5",
                prompt_tokens=1260,
                completion_tokens=190,
                total_tokens=1450,
                frame_count=4,
                estimated_cost_usd=0.008,
                latency_ms=1480,
                success=True,
                created_at=now - timedelta(hours=8),
            ),
        ]
    )


async def seed() -> bool:
    """Create the e2e admin account and demo fixtures. Returns True if
    anything was created."""
    settings = get_settings()
    configure_logging(settings)
    engine = build_engine(settings.database_url)
    try:
        sessionmaker = build_sessionmaker(engine)
        async with sessionmaker() as session:
            count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
            if count > 0:
                logger.info("seed.skipped", users=count)
                return False
            session.add(
                User(
                    id=uuid.uuid4(),
                    email=E2E_ADMIN_EMAIL,
                    hashed_password=PasswordHelper().hash(E2E_ADMIN_PASSWORD),
                    is_active=True,
                    is_superuser=True,
                    is_verified=True,
                    display_name="E2E Admin",
                )
            )
            await _seed_demo_data(session)
            await session.commit()
            logger.info("seed.admin_created", email=E2E_ADMIN_EMAIL)
            return True
    finally:
        await engine.dispose()


async def warm_up_biometrics_model() -> None:
    """Pays the insightface ONNX model's cold-load cost once, up front,
    instead of leaving it for whichever e2e test happens to trigger the
    first real detect-faces call. That first call is otherwise a lazy load
    of real model weights (app.biometrics.recognition), which under
    fullyParallel workers competing for CPU can take well over 20s - long
    enough to time out a test that has no reason to know it just drew the
    short straw. Never raises: a warm-up failure just leaves the same
    lazy-load behavior tests would have hit anyway, no worse than before
    this existed.
    """
    settings = get_settings()
    engine = build_engine(settings.database_url)
    try:
        sessionmaker = build_sessionmaker(engine)
        async with sessionmaker() as session:
            biometrics_settings = await get_biometrics_settings(session)
            await session.commit()
            await download_biometrics_model(
                session, biometrics_settings, settings.biometrics_model_cache_dir
            )
        logger.info("seed.biometrics_model_warmed")
    except Exception as exc:
        logger.warning("seed.biometrics_model_warmup_failed", error=str(exc))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
