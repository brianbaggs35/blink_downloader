"""Camera baselines (passive accumulation + feedback reinforcement) and
feedback-driven few-shot prompt examples."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.learning import (
    baseline_context_for,
    feedback_examples_for,
    record_feedback,
    reinforce_baseline_from_feedback,
    update_baseline,
)
from app.ai.models import Analysis, AnalysisTier, CameraBaseline, FeedbackVerdict, SuspicionLabel
from app.blink.models import BlinkAccount, Camera, Clip
from app.config import get_settings
from app.security.crypto import SecretBox
from app.users.models import User


async def _make_user(session: AsyncSession) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_camera(session: AsyncSession) -> Camera:
    box = SecretBox(get_settings().encryption_key)
    account = BlinkAccount(
        encrypted_username=box.encrypt("a@example.com"),
        encrypted_password=box.encrypt("hunter2"),
        encrypted_token_data=box.encrypt("{}"),
    )
    session.add(account)
    await session.flush()
    camera = Camera(
        blink_account_id=account.id,
        blink_camera_id="cam-1",
        blink_network_id="net-1",
        name="Driveway",
        camera_type="catalina",
    )
    session.add(camera)
    await session.commit()
    await session.refresh(camera)
    return camera


async def _make_clip_and_analysis(
    session: AsyncSession, camera: Camera, *, recorded_at: datetime | None = None
) -> tuple[Clip, Analysis]:
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id=f"/media/{uuid.uuid4()}.mp4",
        recorded_at=recorded_at or datetime(2026, 7, 20, 14, 30, tzinfo=UTC),
        raw_metadata={},
    )
    session.add(clip)
    await session.flush()
    analysis = Analysis(
        clip_id=clip.id,
        summary="A person walks up and leaves a package.",
        suspicion_score=0.1,
        suspicion_label=SuspicionLabel.ROUTINE,
        tier=AnalysisTier.TIER1,
        detected_entities=[
            {"type": "person", "label": "delivery driver", "confidence": 0.9, "bbox": None}
        ],
    )
    session.add(analysis)
    await session.commit()
    await session.refresh(clip)
    await session.refresh(analysis)
    return clip, analysis


async def _current_baseline(session: AsyncSession, camera_id: uuid.UUID) -> CameraBaseline | None:
    return (
        await session.execute(select(CameraBaseline).where(CameraBaseline.camera_id == camera_id))
    ).scalar_one_or_none()


# ------------------------------------------------------------- baselines


async def test_update_baseline_creates_the_row_on_first_observation(
    app_session: AsyncSession,
) -> None:
    camera = await _make_camera(app_session)
    recorded_at = datetime(2026, 7, 20, 14, 30, tzinfo=UTC)
    await update_baseline(app_session, camera.id, recorded_at, ["person", "vehicle"])
    await app_session.commit()

    row = await _current_baseline(app_session, camera.id)
    assert row is not None
    assert row.hourly_entity_counts == {"14": {"person": 1, "vehicle": 1}}
    assert row.total_observations == 1


async def test_update_baseline_accumulates_across_calls(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    recorded_at = datetime(2026, 7, 20, 14, 30, tzinfo=UTC)
    await update_baseline(app_session, camera.id, recorded_at, ["person"])
    await update_baseline(app_session, camera.id, recorded_at, ["person", "animal"])
    await app_session.commit()

    row = await _current_baseline(app_session, camera.id)
    assert row is not None
    assert row.hourly_entity_counts == {"14": {"person": 2, "animal": 1}}
    assert row.total_observations == 2


async def test_update_baseline_keeps_hours_separate(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    await update_baseline(
        app_session, camera.id, datetime(2026, 7, 20, 8, 0, tzinfo=UTC), ["person"]
    )
    await update_baseline(
        app_session, camera.id, datetime(2026, 7, 20, 20, 0, tzinfo=UTC), ["vehicle"]
    )
    await app_session.commit()

    row = await _current_baseline(app_session, camera.id)
    assert row is not None
    assert row.hourly_entity_counts == {"8": {"person": 1}, "20": {"vehicle": 1}}


async def test_update_baseline_with_no_entities_is_a_noop(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    await update_baseline(app_session, camera.id, datetime.now(UTC), [])
    await app_session.commit()
    assert await _current_baseline(app_session, camera.id) is None


async def test_reinforce_baseline_applies_extra_weight(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    recorded_at = datetime(2026, 7, 20, 14, 30, tzinfo=UTC)
    await update_baseline(app_session, camera.id, recorded_at, ["person"])
    await reinforce_baseline_from_feedback(app_session, camera.id, recorded_at, ["person"])
    await app_session.commit()

    row = await _current_baseline(app_session, camera.id)
    assert row is not None
    # 1 (passive) + 3 (feedback weight) = 4; total_observations untouched by reinforcement.
    assert row.hourly_entity_counts == {"14": {"person": 4}}
    assert row.total_observations == 1


async def test_baseline_context_is_none_with_no_history(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    assert await baseline_context_for(app_session, camera.id, 14) is None


async def test_baseline_context_is_none_for_an_hour_with_no_observations(
    app_session: AsyncSession,
) -> None:
    camera = await _make_camera(app_session)
    await update_baseline(
        app_session, camera.id, datetime(2026, 7, 20, 8, 0, tzinfo=UTC), ["person"]
    )
    await app_session.commit()
    assert await baseline_context_for(app_session, camera.id, 14) is None


async def test_baseline_context_summarizes_top_entities(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    recorded_at = datetime(2026, 7, 20, 14, 0, tzinfo=UTC)
    for _ in range(5):
        await update_baseline(app_session, camera.id, recorded_at, ["person"])
    for _ in range(2):
        await update_baseline(app_session, camera.id, recorded_at, ["vehicle"])
    await app_session.commit()

    context = await baseline_context_for(app_session, camera.id, 14)
    assert context is not None
    assert "person (5x)" in context
    assert "vehicle (2x)" in context
    assert context.index("person") < context.index("vehicle")  # sorted by count desc


# ------------------------------------------------------- feedback examples


async def test_feedback_examples_empty_with_no_feedback(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    assert await feedback_examples_for(app_session, camera.id, 5) == []


async def test_feedback_examples_zero_limit_returns_empty_without_querying(
    app_session: AsyncSession,
) -> None:
    camera = await _make_camera(app_session)
    assert await feedback_examples_for(app_session, camera.id, 0) == []


async def test_feedback_examples_excludes_correct_verdicts(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    clip, analysis = await _make_clip_and_analysis(app_session, camera)
    user = await _make_user(app_session)
    await record_feedback(app_session, analysis, clip, user.id, FeedbackVerdict.CORRECT, None)
    assert await feedback_examples_for(app_session, camera.id, 5) == []


async def test_feedback_examples_formats_false_positive_and_negative(
    app_session: AsyncSession,
) -> None:
    camera = await _make_camera(app_session)
    clip, analysis = await _make_clip_and_analysis(app_session, camera)
    user = await _make_user(app_session)
    await record_feedback(
        app_session, analysis, clip, user.id, FeedbackVerdict.FALSE_POSITIVE, "just the mail"
    )

    examples = await feedback_examples_for(app_session, camera.id, 5)
    assert len(examples) == 1
    assert "Flagged suspicious, but was actually routine" in examples[0]
    assert analysis.summary in examples[0]


async def test_feedback_examples_formats_false_negative(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    clip, analysis = await _make_clip_and_analysis(app_session, camera)
    user = await _make_user(app_session)
    await record_feedback(
        app_session, analysis, clip, user.id, FeedbackVerdict.FALSE_NEGATIVE, None
    )

    examples = await feedback_examples_for(app_session, camera.id, 5)
    assert len(examples) == 1
    assert "should have been considered suspicious" in examples[0]


async def test_feedback_examples_respects_the_limit(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    user = await _make_user(app_session)
    for i in range(3):
        clip, analysis = await _make_clip_and_analysis(
            app_session, camera, recorded_at=datetime(2026, 7, 20, 14, i, tzinfo=UTC)
        )
        await record_feedback(
            app_session, analysis, clip, user.id, FeedbackVerdict.FALSE_NEGATIVE, None
        )

    examples = await feedback_examples_for(app_session, camera.id, 2)
    assert len(examples) == 2


async def test_feedback_examples_only_for_the_requested_camera(app_session: AsyncSession) -> None:
    camera_a = await _make_camera(app_session)
    camera_b = await _make_camera(app_session)
    clip, analysis = await _make_clip_and_analysis(app_session, camera_a)
    user = await _make_user(app_session)
    await record_feedback(
        app_session, analysis, clip, user.id, FeedbackVerdict.FALSE_POSITIVE, None
    )
    assert await feedback_examples_for(app_session, camera_b.id, 5) == []


# ------------------------------------------------------------ record_feedback


async def test_record_feedback_persists_and_marks_applied(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    clip, analysis = await _make_clip_and_analysis(app_session, camera)
    user = await _make_user(app_session)
    feedback = await record_feedback(
        app_session, analysis, clip, user.id, FeedbackVerdict.CORRECT, "good call"
    )
    assert feedback.applied is True
    assert feedback.verdict == FeedbackVerdict.CORRECT
    assert feedback.note == "good call"
    assert feedback.user_id == user.id


async def test_record_feedback_false_positive_reinforces_the_baseline(
    app_session: AsyncSession,
) -> None:
    camera = await _make_camera(app_session)
    clip, analysis = await _make_clip_and_analysis(
        app_session, camera, recorded_at=datetime(2026, 7, 20, 14, 30, tzinfo=UTC)
    )
    user = await _make_user(app_session)
    await record_feedback(
        app_session, analysis, clip, user.id, FeedbackVerdict.FALSE_POSITIVE, None
    )

    row = await _current_baseline(app_session, camera.id)
    assert row is not None
    assert row.hourly_entity_counts == {"14": {"person": 3}}


async def test_record_feedback_correct_verdict_does_not_touch_the_baseline(
    app_session: AsyncSession,
) -> None:
    camera = await _make_camera(app_session)
    clip, analysis = await _make_clip_and_analysis(app_session, camera)
    user = await _make_user(app_session)
    await record_feedback(app_session, analysis, clip, user.id, FeedbackVerdict.CORRECT, None)
    assert await _current_baseline(app_session, camera.id) is None


async def test_record_feedback_false_positive_with_no_entities_is_a_noop_on_the_baseline(
    app_session: AsyncSession,
) -> None:
    camera = await _make_camera(app_session)
    clip, analysis = await _make_clip_and_analysis(app_session, camera)
    analysis.detected_entities = []
    await app_session.commit()
    user = await _make_user(app_session)
    await record_feedback(
        app_session, analysis, clip, user.id, FeedbackVerdict.FALSE_POSITIVE, None
    )
    assert await _current_baseline(app_session, camera.id) is None
