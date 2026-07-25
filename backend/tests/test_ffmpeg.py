"""ffprobe/ffmpeg wrappers, exercised against real binaries.

A tiny synthetic clip (ffmpeg's own ``testsrc`` generator — no fixture file
needed) stands in for a downloaded Blink clip.
"""

import asyncio
from pathlib import Path

import pytest

from app.video.ffmpeg import FfmpegError, generate_thumbnail, probe_duration_seconds


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
