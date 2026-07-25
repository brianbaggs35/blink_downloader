"""Thin wrappers over the ``ffprobe``/``ffmpeg`` binaries.

Shelling out (rather than a Python binding) keeps this to two well-defined
subprocess calls and avoids taking on another library's maintenance risk for
something this narrow.
"""

import asyncio
import json
from pathlib import Path

from app.logs import get_logger

logger = get_logger(__name__)

PROBE_TIMEOUT_SECONDS = 20
THUMBNAIL_TIMEOUT_SECONDS = 20
THUMBNAIL_OFFSET_SECONDS = "00:00:01"


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


async def generate_thumbnail(source: Path, destination: Path) -> bool:
    """Write a JPEG thumbnail from ``source`` to ``destination``.

    Returns ``False`` (rather than raising) for an unreadable/corrupt source
    clip, matching :func:`probe_duration_seconds`'s policy — a bad thumbnail
    should never block a clip from being downloadable.
    """
    # Must still end in .jpg: ffmpeg's muxer is picked from the output
    # filename's extension, and a bare ".tmp" suffix defeats that.
    tmp_destination = destination.with_name(f"{destination.stem}.tmp{destination.suffix}")
    args = [
        "ffmpeg",
        "-y",
        "-ss",
        THUMBNAIL_OFFSET_SECONDS,
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        "scale=320:-1",
        "-q:v",
        "4",
        "-f",
        "image2",
        str(tmp_destination),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=THUMBNAIL_TIMEOUT_SECONDS)
    except (TimeoutError, OSError) as exc:
        logger.warning("ffmpeg.thumbnail_failed", file=source.name, error=str(exc))
        tmp_destination.unlink(missing_ok=True)
        return False

    if proc.returncode != 0 or not tmp_destination.exists():
        logger.warning(
            "ffmpeg.thumbnail_failed",
            file=source.name,
            stderr=stderr.decode(errors="replace"),
        )
        tmp_destination.unlink(missing_ok=True)
        return False

    tmp_destination.replace(destination)
    return True
