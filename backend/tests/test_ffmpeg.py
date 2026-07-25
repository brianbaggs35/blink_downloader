"""ffprobe/ffmpeg wrappers, exercised against real binaries.

A tiny synthetic clip (ffmpeg's own ``testsrc`` generator — no fixture file
needed) stands in for a downloaded Blink clip.

Real scene-change detection is content-dependent and non-deterministic
enough that it can't reliably be steered to a specific branch (e.g. "more
scene changes than requested keyframes") from black-box clip fixtures
alone, so the timestamp-selection math is also covered directly.
"""

# pyright: reportPrivateUsage=false

import asyncio
from pathlib import Path

import pytest

from app.video.ffmpeg import (
    FfmpegError,
    _evenly_spaced_subset,
    _select_timestamps,
    _uniform_timestamps,
    extract_keyframes,
    generate_thumbnail,
    probe_duration_seconds,
)


@pytest.fixture(scope="module")
def sample_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("clips") / "sample.mp4"

    async def make() -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=64x64:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

    asyncio.run(make())
    assert path.exists()
    return path


@pytest.fixture(scope="module")
def longer_sample_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A longer, higher-motion clip so scene-change detection has something
    to actually find, rather than only exercising the uniform-sampling
    fallback."""
    path = tmp_path_factory.mktemp("clips") / "longer.mp4"

    async def make() -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "mandelbrot=size=96x96:rate=10",
            "-t",
            "6",
            "-pix_fmt",
            "yuv420p",
            str(path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

    asyncio.run(make())
    assert path.exists()
    return path


async def test_probe_duration_returns_expected_length(sample_clip: Path) -> None:
    duration = await probe_duration_seconds(sample_clip)
    assert duration is not None
    assert 1.8 <= duration <= 2.2


async def test_probe_duration_returns_none_for_corrupt_file(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not a real video file")
    assert await probe_duration_seconds(corrupt) is None


async def test_probe_duration_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert await probe_duration_seconds(tmp_path / "does-not-exist.mp4") is None


async def test_probe_duration_raises_on_timeout(
    sample_clip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.video.ffmpeg.PROBE_TIMEOUT_SECONDS", 0)
    with pytest.raises(FfmpegError, match="timed out"):
        await probe_duration_seconds(sample_clip)


async def test_probe_duration_returns_none_for_unexpected_json_shape(
    sample_clip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b'{"format": {}}', b""  # valid JSON, but no "duration" key

    async def fake_exec(*_args: object, **_kwargs: object) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    assert await probe_duration_seconds(sample_clip) is None


async def test_probe_duration_raises_when_binary_missing(
    sample_clip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_exec(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("no such file: ffprobe")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    with pytest.raises(FfmpegError, match="could not run ffprobe"):
        await probe_duration_seconds(sample_clip)


async def test_generate_thumbnail_writes_a_jpeg(sample_clip: Path, tmp_path: Path) -> None:
    destination = tmp_path / "thumb.jpg"
    result = await generate_thumbnail(sample_clip, destination)
    assert result is True
    assert destination.exists()
    assert destination.read_bytes()[:2] == b"\xff\xd8"  # JPEG magic bytes
    assert not destination.with_suffix(".jpg.tmp").exists()


async def test_generate_thumbnail_returns_false_for_corrupt_source(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not a real video file")
    destination = tmp_path / "thumb.jpg"
    result = await generate_thumbnail(corrupt, destination)
    assert result is False
    assert not destination.exists()


async def test_generate_thumbnail_returns_false_on_timeout(
    sample_clip: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.video.ffmpeg.THUMBNAIL_TIMEOUT_SECONDS", 0)
    destination = tmp_path / "thumb.jpg"
    result = await generate_thumbnail(sample_clip, destination)
    assert result is False
    assert not destination.exists()


async def test_extract_keyframes_returns_up_to_the_requested_count(
    longer_sample_clip: Path,
) -> None:
    frames = await extract_keyframes(longer_sample_clip, 4)
    assert 1 <= len(frames) <= 4
    for frame in frames:
        assert frame[:2] == b"\xff\xd8"  # JPEG magic bytes


async def test_extract_keyframes_respects_a_smaller_count(longer_sample_clip: Path) -> None:
    frames = await extract_keyframes(longer_sample_clip, 1)
    assert len(frames) == 1


async def test_extract_keyframes_returns_empty_list_for_zero_count(sample_clip: Path) -> None:
    assert await extract_keyframes(sample_clip, 4) != []  # sanity: sample_clip itself works
    assert await extract_keyframes(sample_clip, 0) == []


async def test_extract_keyframes_returns_empty_for_corrupt_source(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not a real video file")
    assert await extract_keyframes(corrupt, 4) == []


async def test_extract_keyframes_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert await extract_keyframes(tmp_path / "does-not-exist.mp4", 4) == []


async def test_extract_keyframes_degrades_to_empty_list_on_timeout(
    longer_sample_clip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.video.ffmpeg.KEYFRAME_TIMEOUT_SECONDS", 0)
    assert await extract_keyframes(longer_sample_clip, 4) == []


async def test_extract_keyframes_returns_empty_when_ffmpeg_binary_missing(
    longer_sample_clip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_exec(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("no such file: ffmpeg")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    assert await extract_keyframes(longer_sample_clip, 4) == []


async def test_extract_keyframes_falls_back_to_a_single_frame_when_duration_unprobeable(
    longer_sample_clip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_probe(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.video.ffmpeg.probe_duration_seconds", fake_probe)
    frames = await extract_keyframes(longer_sample_clip, 4)
    assert len(frames) == 1
    assert frames[0][:2] == b"\xff\xd8"


async def test_extract_keyframes_recovers_when_probe_raises_ffmpeg_error(
    longer_sample_clip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_probe(*_args: object, **_kwargs: object) -> None:
        raise FfmpegError("ffprobe timed out")

    monkeypatch.setattr("app.video.ffmpeg.probe_duration_seconds", fake_probe)
    frames = await extract_keyframes(longer_sample_clip, 4)
    assert len(frames) == 1  # falls back to a single frame, doesn't propagate


# ------------------------------------------------------- timestamp selection


def test_uniform_timestamps_single_point_is_the_midpoint() -> None:
    assert _uniform_timestamps(10.0, 1) == [5.0]


def test_uniform_timestamps_spans_five_to_ninety_five_percent() -> None:
    assert _uniform_timestamps(10.0, 3) == pytest.approx([0.5, 5.0, 9.5])


def test_evenly_spaced_subset_returns_everything_when_within_budget() -> None:
    assert _evenly_spaced_subset([1.0, 2.0], 4) == [1.0, 2.0]


def test_evenly_spaced_subset_picks_the_midpoint_for_a_single_slot() -> None:
    assert _evenly_spaced_subset([1.0, 2.0, 3.0, 4.0, 5.0], 1) == [3.0]


def test_evenly_spaced_subset_spreads_indices_across_the_range() -> None:
    items = [float(i) for i in range(10)]
    assert _evenly_spaced_subset(items, 3) == [0.0, 4.0, 9.0]


def test_select_timestamps_prefers_scene_changes_when_there_are_enough() -> None:
    scene_changes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    result = _select_timestamps(scene_changes, duration=10.0, count=3)
    assert result == [1.0, 5.0, 9.0]


def test_select_timestamps_fills_remaining_slots_with_uniform_samples() -> None:
    result = _select_timestamps([5.0], duration=10.0, count=4)
    assert 5.0 in result
    assert len(result) == 4
    assert result == sorted(result)


def test_select_timestamps_with_no_scene_changes_is_pure_uniform() -> None:
    result = _select_timestamps([], duration=10.0, count=3)
    assert result == pytest.approx([0.5, 5.0, 9.5])
