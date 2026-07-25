"""Thin wrappers over the ``ffprobe``/``ffmpeg`` binaries.

Shelling out (rather than a Python binding) keeps this to a handful of
well-defined subprocess calls and avoids taking on another library's
maintenance risk for something this narrow.
"""

import asyncio
import json
import re
from pathlib import Path

from app.logs import get_logger

logger = get_logger(__name__)

PROBE_TIMEOUT_SECONDS = 20
THUMBNAIL_TIMEOUT_SECONDS = 20
THUMBNAIL_OFFSET_SECONDS = "00:00:01"
THUMBNAIL_MAX_WIDTH = 320

REFERENCE_FRAME_TIMEOUT_SECONDS = 20
REFERENCE_FRAME_OFFSET_SECONDS = "00:00:01"
REFERENCE_FRAME_MAX_DIMENSION = 1024
"""Higher-res than a library thumbnail: a household member draws a vehicle
outline over this frame, so it needs to be clear enough to trace by hand."""

KEYFRAME_TIMEOUT_SECONDS = 30
KEYFRAME_MAX_DIMENSION = 768
"""Longest edge in pixels for a keyframe sent to a VLM. Vision token cost
scales with image size, so this trades detail for the token budget — 768px
is enough to identify a person/vehicle/package without paying for more."""
SCENE_CHANGE_THRESHOLD = 0.35
_PTS_TIME_RE = re.compile(r"pts_time:([\d.]+)")


class FfmpegError(Exception):
    """ffprobe/ffmpeg failed, timed out, or produced no usable output."""


async def probe_duration_seconds(path: Path) -> float | None:
    """Return the clip's duration, or ``None`` if it can't be determined.

    Never raises for a merely-unreadable/corrupt file — a clip the pipeline
    can't probe should still be downloadable and playable client-side; only
    a genuinely unexpected failure (binary missing, process error) surfaces
    as :class:`FfmpegError`.
    """
    args = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise FfmpegError(f"ffprobe timed out probing {path.name}") from exc
    except OSError as exc:
        raise FfmpegError(f"could not run ffprobe: {exc}") from exc

    if proc.returncode != 0:
        logger.warning("ffprobe.failed", file=path.name, stderr=stderr.decode(errors="replace"))
        return None

    try:
        duration = json.loads(stdout)["format"]["duration"]
        return round(float(duration), 2)
    # json.JSONDecodeError is a ValueError subclass, already covered here.
    # `# fmt: skip`: ruff's formatter mis-strips this tuple's parens, which
    # changes an unambiguous `except (A, B):` into a legal-but-startling bare
    # exception-tuple (Python allows unparenthesized except-tuples of 3+
    # items — verified empirically; not something to rely on readability-wise).
    except (KeyError, ValueError, TypeError):  # fmt: skip
        logger.warning("ffprobe.unparseable_output", file=path.name)
        return None


async def _capture_frame_to_file(
    source: Path,
    destination: Path,
    *,
    offset_seconds: str,
    scale_filter: str,
    quality: str,
    timeout_seconds: float,
    log_event: str,
) -> bool:
    """Shared implementation behind :func:`generate_thumbnail` and
    :func:`capture_reference_frame`: grab one frame to a file, never
    raising for an unreadable/corrupt source (returns ``False`` instead)."""
    # Must still end in .jpg: ffmpeg's muxer is picked from the output
    # filename's extension, and a bare ".tmp" suffix defeats that.
    tmp_destination = destination.with_name(f"{destination.stem}.tmp{destination.suffix}")
    args = [
        "ffmpeg",
        "-y",
        "-ss",
        offset_seconds,
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        scale_filter,
        "-q:v",
        quality,
        "-f",
        "image2",
        str(tmp_destination),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except (TimeoutError, OSError) as exc:
        logger.warning(log_event, file=source.name, error=str(exc))
        tmp_destination.unlink(missing_ok=True)
        return False

    if proc.returncode != 0 or not tmp_destination.exists():
        logger.warning(log_event, file=source.name, stderr=stderr.decode(errors="replace"))
        tmp_destination.unlink(missing_ok=True)
        return False

    tmp_destination.replace(destination)
    return True


async def generate_thumbnail(source: Path, destination: Path) -> bool:
    """Write a JPEG thumbnail from ``source`` to ``destination``.

    Returns ``False`` (rather than raising) for an unreadable/corrupt source
    clip, matching :func:`probe_duration_seconds`'s policy — a bad thumbnail
    should never block a clip from being downloadable.
    """
    return await _capture_frame_to_file(
        source,
        destination,
        offset_seconds=THUMBNAIL_OFFSET_SECONDS,
        scale_filter=f"scale={THUMBNAIL_MAX_WIDTH}:-1",
        quality="4",
        timeout_seconds=THUMBNAIL_TIMEOUT_SECONDS,
        log_event="ffmpeg.thumbnail_failed",
    )


async def capture_reference_frame(source: Path, destination: Path) -> bool:
    """Write a higher-resolution JPEG frame from ``source`` for a household
    member to draw a vehicle outline over. Same never-raises contract as
    :func:`generate_thumbnail`."""
    return await _capture_frame_to_file(
        source,
        destination,
        offset_seconds=REFERENCE_FRAME_OFFSET_SECONDS,
        scale_filter=f"scale='min({REFERENCE_FRAME_MAX_DIMENSION},iw)':-2",
        quality="3",
        timeout_seconds=REFERENCE_FRAME_TIMEOUT_SECONDS,
        log_event="ffmpeg.reference_frame_failed",
    )


async def extract_keyframes(source: Path, count: int) -> list[bytes]:
    """Pick up to ``count`` representative frames from ``source`` and return
    each as JPEG bytes, scaled down for token-efficient VLM input.

    Combines scene-change detection (catches something suddenly appearing
    mid-clip) with uniform sampling (guarantees coverage even for a clip
    with no detected scene changes at all — common for short, continuous
    security footage). Never raises for a corrupt/unreadable source; an
    unanalyzable clip should not block the pipeline, just yield no frames.
    """
    if count <= 0:
        return []

    try:
        duration = await probe_duration_seconds(source)
    except FfmpegError as exc:
        logger.warning("ffmpeg.keyframe_probe_failed", file=source.name, error=str(exc))
        duration = None
    if not duration or duration <= 0:
        frame = await _extract_frame_at(source, 0.0)
        return [frame] if frame else []

    scene_changes = await _scene_change_timestamps(source, duration)
    timestamps = _select_timestamps(scene_changes, duration, count)

    frames: list[bytes] = []
    for ts in timestamps:
        frame = await _extract_frame_at(source, ts)
        if frame:
            frames.append(frame)
    return frames


async def _scene_change_timestamps(source: Path, duration: float) -> list[float]:
    args = [
        "ffmpeg",
        "-i",
        str(source),
        "-vf",
        f"select='gt(scene,{SCENE_CHANGE_THRESHOLD})',showinfo",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=KEYFRAME_TIMEOUT_SECONDS)
    except (TimeoutError, OSError) as exc:
        logger.warning("ffmpeg.scene_detect_failed", file=source.name, error=str(exc))
        return []

    matches = _PTS_TIME_RE.findall(stderr.decode(errors="replace"))
    return sorted({round(float(m), 3) for m in matches if float(m) < duration})


def _uniform_timestamps(duration: float, count: int) -> list[float]:
    if count <= 1:
        return [duration / 2]
    start, end = duration * 0.05, duration * 0.95
    step = (end - start) / (count - 1)
    return [start + i * step for i in range(count)]


def _evenly_spaced_subset(items: list[float], count: int) -> list[float]:
    if len(items) <= count:
        return items
    if count == 1:
        return [items[len(items) // 2]]
    step = (len(items) - 1) / (count - 1)
    indices = sorted({round(i * step) for i in range(count)})
    return [items[i] for i in indices]


def _select_timestamps(scene_changes: list[float], duration: float, count: int) -> list[float]:
    """Prefer detected scene changes; fill any remaining slots with uniform
    samples that don't land right on top of one already picked."""
    scene_changes = sorted(set(scene_changes))
    if len(scene_changes) >= count:
        return _evenly_spaced_subset(scene_changes, count)

    remaining = count - len(scene_changes)
    min_gap = max(duration * 0.03, 0.3)
    pool = _uniform_timestamps(duration, count * 3)
    candidates = [t for t in pool if all(abs(t - sc) >= min_gap for sc in scene_changes)]
    fillers = _evenly_spaced_subset(candidates, remaining)
    return sorted(scene_changes + fillers)


async def _extract_frame_at(source: Path, timestamp: float) -> bytes | None:
    args = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{max(timestamp, 0.0):.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        f"scale='min({KEYFRAME_MAX_DIMENSION},iw)':-2",
        "-q:v",
        "3",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=KEYFRAME_TIMEOUT_SECONDS
        )
    except (TimeoutError, OSError) as exc:
        logger.warning("ffmpeg.keyframe_extract_failed", file=source.name, error=str(exc))
        return None

    if proc.returncode != 0 or not stdout:
        logger.warning(
            "ffmpeg.keyframe_extract_failed",
            file=source.name,
            stderr=stderr.decode(errors="replace"),
        )
        return None
    return stdout
