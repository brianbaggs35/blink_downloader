"""Local-only face detection + embedding engine, wrapping insightface/onnxruntime.

Nothing here makes a network call at inference time: models are loaded once
from an on-disk cache (downloaded from insightface's release assets the
first time a given model pack is used, then reused) and every image passed
in stays in this process's memory. See app.biometrics.models's module
docstring for why that matters.

Kept deliberately free of database/settings access — callers (see
app.biometrics.service) resolve model pack, provider preference, and the
model cache directory from settings/DB and pass plain values in, the same
layering as app.video.ffmpeg and app.vehicles.geometry.
"""

# insightface and onnxruntime ship no type stubs, so every attribute we
# touch on their objects (Face.bbox, FaceAnalysis.get, ...) types as
# Unknown — the same class of third-party-stub friction as blinkpy in
# app/blink/service.py.
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false

import io
import shutil

# See _gpu_actually_usable's own docstring for why this is used safely.
import subprocess  # nosec B404
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import onnxruntime
from insightface.app import FaceAnalysis
from PIL import Image

from app.biometrics.models import ExecutionProviderPreference, ModelPack
from app.logs import get_logger

logger = get_logger(__name__)

# Makes the CUDA/cuDNN shared libraries installed via the onnxruntime-gpu
# [cuda,cudnn] extras (pip-installed NVIDIA wheels, not a system CUDA
# Toolkit - see pyproject.toml) actually discoverable to onnxruntime's CUDA
# execution provider. A safe no-op on the plain (arm64/CPU-only) build this
# app also supports: onnxruntime reports no CUDA version info baked in, so
# this returns immediately without touching anything.
onnxruntime.preload_dlls()

# insightface's own documented default input resolution for the SCRFD
# detector — large enough to find faces that aren't filling the frame
# (typical for a security camera's wide field of view) without the extra
# cost of the next size up.
DETECTION_SIZE = (640, 640)

CUDA_PROVIDER = "CUDAExecutionProvider"
CPU_PROVIDER = "CPUExecutionProvider"


class RecognitionError(Exception):
    """The image bytes handed in couldn't be decoded."""


class ModelLoadError(Exception):
    """Building a model pack's inference sessions failed - most commonly a
    first-use model download that couldn't reach insightface's release
    assets, or a cache directory that isn't writable. Callers on the AI
    analysis path treat this as an expected, non-retryable reason to skip
    recognition for this pass rather than losing an already-computed VLM
    result over it (see app.ai.pipeline._recognize_and_label)."""


@dataclass
class DetectedFace:
    bbox: tuple[float, float, float, float]  # normalized x, y, w, h
    confidence: float
    embedding: list[float]  # 512-dim, L2-normalized


@dataclass
class FaceMatch:
    person_id: uuid.UUID
    score: float


_engines: dict[tuple[ModelPack, tuple[str, ...]], FaceAnalysis] = {}
_engines_lock = threading.Lock()


def available_providers() -> list[str]:
    """What "auto" would actually pick in this process right now - shown in
    Settings so an admin can tell whether choosing it would use CUDA before
    they do. Deliberately not just onnxruntime.get_available_providers():
    that reflects what onnxruntime-gpu was compiled with, not whether this
    specific container can reach a real GPU (see resolve_providers/
    _gpu_actually_usable) - showing it unfiltered here would have this
    panel confidently claim "GPU available" on, say, a plain `make dev`
    container on a real GPU host, when auto would silently fall back to
    CPU because dev's own compose file requests no device passthrough."""
    reported = onnxruntime.get_available_providers()
    if CUDA_PROVIDER in reported and not _gpu_actually_usable():
        return [p for p in reported if p != CUDA_PROVIDER]
    return list(reported)


@lru_cache(maxsize=1)
def _gpu_actually_usable() -> bool:
    """Whether a real, driver-accessible GPU exists in *this* process's
    environment - deliberately not the same question as whether
    CUDAExecutionProvider is in get_available_providers(), which reflects
    what onnxruntime-gpu was compiled with, not what this specific
    container can reach. nvidia-container-toolkit injects nvidia-smi (and
    the driver libraries behind it) only into containers actually granted
    GPU access (see docker-compose.gpu.yml/prod.gpu.yml); the plain
    dev/prod/test compose files request no device reservation at all, so
    nvidia-smi is simply absent there, and this correctly returns False
    without ever attempting (and failing) a real CUDA session build.
    Cached for the process's lifetime - this can't change without a
    container restart."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return False
    try:
        # nvidia_smi is shutil.which's own resolved absolute path for a
        # hardcoded binary name, never user input; no shell.
        result = subprocess.run(  # noqa: S603 # nosec B603
            [nvidia_smi], capture_output=True, timeout=5, check=False
        )
    except OSError:
        return False
    return result.returncode == 0


def resolve_providers(preference: ExecutionProviderPreference) -> list[str]:
    """ "auto" uses CUDA when onnxruntime reports it available in this
    process AND a real GPU is reachable, else falls back to CPU. GPU is
    never assumed - onnxruntime-gpu only ships x86_64 wheels at all, so
    this also keeps arm64 hosts correct without any platform-specific
    branching here."""
    if preference is ExecutionProviderPreference.CPU:
        return [CPU_PROVIDER]
    available = onnxruntime.get_available_providers()
    if CUDA_PROVIDER in available and _gpu_actually_usable():
        return [CUDA_PROVIDER, CPU_PROVIDER]
    return [CPU_PROVIDER]


def _get_engine(
    model_pack: ModelPack, providers: Sequence[str], model_cache_dir: Path
) -> FaceAnalysis:
    """Loading a model pack means reading its ONNX weights off disk and
    building onnxruntime sessions for them - real work worth doing once per
    (pack, providers) combination and reusing. The lock only serializes
    construction (rare - once per combination for the process's lifetime);
    a built FaceAnalysis's sessions are safe to call concurrently afterward
    (onnxruntime supports concurrent Run() calls on one session), so normal
    detect_faces calls never contend on it."""
    key = (model_pack, tuple(providers))
    with _engines_lock:
        engine = _engines.get(key)
        if engine is not None:
            return engine
        logger.info(
            "biometrics.engine_loading", model_pack=model_pack.value, providers=list(providers)
        )
        try:
            engine = FaceAnalysis(
                name=model_pack.value, root=str(model_cache_dir), providers=list(providers)
            )
            ctx_id = 0 if CUDA_PROVIDER in providers else -1
            engine.prepare(ctx_id=ctx_id, det_size=DETECTION_SIZE)
        except Exception as exc:
            # insightface/onnxruntime raise a mix of untyped exceptions for
            # "couldn't download the model" and "couldn't build a session
            # from it" (network errors, corrupt/partial zip, unwritable
            # cache dir, ...) - there is no single documented type to catch
            # narrowly, so this boundary converts whatever it was into one
            # typed error the rest of the app can handle deliberately.
            logger.warning(
                "biometrics.engine_load_failed",
                model_pack=model_pack.value,
                providers=list(providers),
                error=str(exc),
            )
            raise ModelLoadError(
                f"Could not load the {model_pack.value} model pack: {exc}"
            ) from exc
        _engines[key] = engine
        return engine


def ensure_model_ready(
    model_pack: ModelPack, provider_preference: ExecutionProviderPreference, model_cache_dir: Path
) -> list[str]:
    """Forces the model pack to be downloaded (if not already cached) and
    loaded, without needing a real image - what Settings' "verify model"
    action calls so an admin gets a clear pass/fail the moment they enable
    biometrics, instead of finding out during the next real clip analysis.
    Returns the execution providers the loaded engine actually ended up
    using. Raises ModelLoadError on failure."""
    providers = resolve_providers(provider_preference)
    _get_engine(model_pack, providers, model_cache_dir)
    return providers


def detect_faces(
    image_bytes: bytes,
    *,
    model_pack: ModelPack,
    provider_preference: ExecutionProviderPreference,
    model_cache_dir: Path,
) -> list[DetectedFace]:
    """Detect every face in ``image_bytes`` (anything OpenCV can decode,
    e.g. a JPEG frame) and return each with a normalized bounding box - same
    (x, y, w, h) 0-1 convention as app.ai.providers.DetectedEntityResult, so
    the two can be correlated directly - and a 512-dim L2-normalized
    embedding ready for cosine-similarity matching.

    Synchronous and CPU-bound; callers on the async path should wrap this in
    ``asyncio.to_thread``.
    """
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise RecognitionError("Could not decode image for face detection.")

    providers = resolve_providers(provider_preference)
    engine = _get_engine(model_pack, providers, model_cache_dir)
    height, width = image.shape[:2]

    faces: list[DetectedFace] = []
    for face in engine.get(image):
        x1, y1, x2, y2 = (float(v) for v in face.bbox)
        faces.append(
            DetectedFace(
                bbox=(x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height),
                confidence=float(face.det_score),
                embedding=face.normed_embedding.tolist(),
            )
        )
    return faces


def crop_face_thumbnail(
    image_bytes: bytes, bbox: tuple[float, float, float, float], *, padding: float = 0.3
) -> bytes:
    """Crop the face at ``bbox`` (normalized x, y, w, h - the convention
    detect_faces returns) out of ``image_bytes``, padded so the saved
    sample shows a bit of context around the face rather than a razor-tight
    oval, and re-encoded as JPEG."""
    with Image.open(io.BytesIO(image_bytes)) as image:
        width, height = image.size
        x, y, w, h = bbox
        pad_x, pad_y = w * padding, h * padding
        left = max(0, round((x - pad_x) * width))
        top = max(0, round((y - pad_y) * height))
        right = min(width, round((x + w + pad_x) * width))
        bottom = min(height, round((y + h + pad_y) * height))
        cropped = image.convert("RGB").crop((left, top, right, bottom))
        buffer = io.BytesIO()
        cropped.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Embeddings from detect_faces are already L2-normalized, making this a
    plain dot product - but norms are recomputed rather than assumed, since
    a stored embedding could in principle be handed in from anywhere."""
    a_arr = np.asarray(a, dtype=np.float32)
    b_arr = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(a_arr) * np.linalg.norm(b_arr))
    if denom <= 0.0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / denom)


def best_match(
    query_embedding: Sequence[float],
    positive_candidates: Sequence[tuple[uuid.UUID, Sequence[float]]],
    negative_candidates: Sequence[tuple[uuid.UUID, Sequence[float]]],
    threshold: float,
) -> FaceMatch | None:
    """Both candidate lists are (person_id, embedding) pairs - typically
    every enrolled sample across every person (household scale: at most a
    few hundred rows, cheap to compare against in plain Python).

    A person's own negative samples (see FaceEmbedding.is_negative - faces a
    household member confirmed were NOT them, via the "report" action on a
    recognized clip) veto a match to them: if the query face is at least as
    close to one of their negatives as to their best positive, that's the
    known false-positive face pattern recurring, and reporting it must
    actually change future behavior rather than just relabel one clip.

    Returns the closest positive match at or above ``threshold`` that isn't
    vetoed this way, or None if nobody clears it."""
    negative_best: dict[uuid.UUID, float] = {}
    for person_id, embedding in negative_candidates:
        score = cosine_similarity(query_embedding, embedding)
        if person_id not in negative_best or score > negative_best[person_id]:
            negative_best[person_id] = score

    best: FaceMatch | None = None
    for person_id, embedding in positive_candidates:
        score = cosine_similarity(query_embedding, embedding)
        if score < threshold or score <= negative_best.get(person_id, -1.0):
            continue
        if best is None or score > best.score:
            best = FaceMatch(person_id=person_id, score=score)
    return best
