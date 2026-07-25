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
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime
from insightface.app import FaceAnalysis
from PIL import Image

from app.biometrics.models import ExecutionProviderPreference, ModelPack
from app.logs import get_logger

logger = get_logger(__name__)

# insightface's own documented default input resolution for the SCRFD
# detector — large enough to find faces that aren't filling the frame
# (typical for a security camera's wide field of view) without the extra
# cost of the next size up.
DETECTION_SIZE = (640, 640)

CUDA_PROVIDER = "CUDAExecutionProvider"
CPU_PROVIDER = "CPUExecutionProvider"


class RecognitionError(Exception):
    """The image bytes handed in couldn't be decoded."""


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
    """What onnxruntime actually reports as usable in this process - shown
    in Settings so an admin can tell whether "auto" would pick CUDA before
    they choose it."""
    return list(onnxruntime.get_available_providers())


def resolve_providers(preference: ExecutionProviderPreference) -> list[str]:
    """"auto" uses CUDA when onnxruntime reports it available in this
    process, else falls back to CPU. GPU is never assumed - onnxruntime-gpu
    only ships x86_64 wheels at all, so this also keeps arm64 hosts correct
    without any platform-specific branching here."""
    if preference is ExecutionProviderPreference.CPU:
        return [CPU_PROVIDER]
    available = onnxruntime.get_available_providers()
    if CUDA_PROVIDER in available:
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
        engine = FaceAnalysis(
            name=model_pack.value, root=str(model_cache_dir), providers=list(providers)
        )
        ctx_id = 0 if CUDA_PROVIDER in providers else -1
        engine.prepare(ctx_id=ctx_id, det_size=DETECTION_SIZE)
        _engines[key] = engine
        return engine


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
    if denom == 0.0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / denom)


def best_match(
    query_embedding: Sequence[float],
    candidates: Sequence[tuple[uuid.UUID, Sequence[float]]],
    threshold: float,
) -> FaceMatch | None:
    """``candidates`` is (person_id, embedding) pairs - typically every
    enrolled sample across every person (household scale: at most a few
    hundred rows, cheap to compare against in plain Python). Returns the
    closest match at or above ``threshold``, or None if nobody clears it."""
    best: FaceMatch | None = None
    for person_id, embedding in candidates:
        score = cosine_similarity(query_embedding, embedding)
        if score >= threshold and (best is None or score > best.score):
            best = FaceMatch(person_id=person_id, score=score)
    return best
