"""app/biometrics/recognition.py: insightface faked at the FaceAnalysis
class boundary, since constructing a real one triggers a model download —
never a real network call, matching the blinkpy/AI-provider convention used
elsewhere in this project.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false
# White-box: clears the private engine cache between tests for isolation.
# pyright: reportPrivateUsage=false

import uuid
from pathlib import Path
from typing import Any, ClassVar

import cv2
import numpy as np
import pytest

from app.biometrics import recognition
from app.biometrics.models import ExecutionProviderPreference, ModelPack
from app.biometrics.recognition import (
    RecognitionError,
    available_providers,
    best_match,
    cosine_similarity,
    detect_faces,
    resolve_providers,
)

CACHE_DIR = Path("/fake/insightface/cache")


def _tiny_jpeg_bytes(width: int = 20, height: int = 10) -> bytes:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


class FakeFace:
    def __init__(
        self, bbox: tuple[float, float, float, float], det_score: float, embedding: list[float]
    ) -> None:
        self.bbox = np.array(bbox, dtype=np.float32)
        self.det_score = det_score
        self.normed_embedding = np.array(embedding, dtype=np.float32)


class FakeFaceAnalysis:
    """Stands in for insightface.app.FaceAnalysis — constructing the real
    class triggers a model download from the network on first use."""

    instances: ClassVar[list[FakeFaceAnalysis]] = []

    def __init__(self, *, name: str, root: str, providers: list[str]) -> None:
        self.name = name
        self.root = root
        self.providers = providers
        self.prepare_calls: list[dict[str, Any]] = []
        self.faces: list[FakeFace] = []
        FakeFaceAnalysis.instances.append(self)

    def prepare(self, *, ctx_id: int, det_size: tuple[int, int]) -> None:
        self.prepare_calls.append({"ctx_id": ctx_id, "det_size": det_size})

    def get(self, image: object) -> list[FakeFace]:
        return self.faces


@pytest.fixture(autouse=True)
def _fake_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recognition, "FaceAnalysis", FakeFaceAnalysis)
    recognition._engines.clear()
    FakeFaceAnalysis.instances.clear()


# ---------------------------------------------------------- available_providers


def test_available_providers_reflects_onnxruntime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        recognition.onnxruntime, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    assert available_providers() == ["CPUExecutionProvider"]


# ----------------------------------------------------------- resolve_providers


def test_resolve_providers_cpu_preference_ignores_available_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recognition.onnxruntime,
        "get_available_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    assert resolve_providers(ExecutionProviderPreference.CPU) == ["CPUExecutionProvider"]


def test_resolve_providers_auto_falls_back_to_cpu_when_no_cuda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recognition.onnxruntime, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    assert resolve_providers(ExecutionProviderPreference.AUTO) == ["CPUExecutionProvider"]


def test_resolve_providers_auto_prefers_cuda_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recognition.onnxruntime,
        "get_available_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    assert resolve_providers(ExecutionProviderPreference.AUTO) == [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]


# -------------------------------------------------------------- detect_faces


def test_detect_faces_raises_on_undecodable_bytes() -> None:
    with pytest.raises(RecognitionError):
        detect_faces(
            b"not an image",
            model_pack=ModelPack.BUFFALO_SC,
            provider_preference=ExecutionProviderPreference.CPU,
            model_cache_dir=CACHE_DIR,
        )


def test_detect_faces_returns_empty_list_when_engine_finds_nobody() -> None:
    faces = detect_faces(
        _tiny_jpeg_bytes(),
        model_pack=ModelPack.BUFFALO_SC,
        provider_preference=ExecutionProviderPreference.CPU,
        model_cache_dir=CACHE_DIR,
    )
    assert faces == []


def test_detect_faces_normalizes_bbox_and_passes_through_embedding() -> None:
    image_bytes = _tiny_jpeg_bytes(width=200, height=100)
    # Prime the engine, then hand it a face to return on the next call.
    detect_faces(
        image_bytes,
        model_pack=ModelPack.BUFFALO_SC,
        provider_preference=ExecutionProviderPreference.CPU,
        model_cache_dir=CACHE_DIR,
    )
    engine = FakeFaceAnalysis.instances[0]
    engine.faces = [
        FakeFace(bbox=(20.0, 10.0, 60.0, 50.0), det_score=0.91, embedding=[0.1, 0.2, 0.3])
    ]

    faces = detect_faces(
        image_bytes,
        model_pack=ModelPack.BUFFALO_SC,
        provider_preference=ExecutionProviderPreference.CPU,
        model_cache_dir=CACHE_DIR,
    )
    assert len(faces) == 1
    face = faces[0]
    assert face.bbox == pytest.approx((0.1, 0.1, 0.2, 0.4))
    assert face.confidence == pytest.approx(0.91)
    assert face.embedding == pytest.approx([0.1, 0.2, 0.3])


def test_detect_faces_reuses_cached_engine_for_same_pack_and_providers() -> None:
    image_bytes = _tiny_jpeg_bytes()
    for _ in range(2):
        detect_faces(
            image_bytes,
            model_pack=ModelPack.BUFFALO_SC,
            provider_preference=ExecutionProviderPreference.CPU,
            model_cache_dir=CACHE_DIR,
        )
    assert len(FakeFaceAnalysis.instances) == 1
    engine = FakeFaceAnalysis.instances[0]
    assert engine.prepare_calls == [{"ctx_id": -1, "det_size": recognition.DETECTION_SIZE}]


def test_detect_faces_builds_a_new_engine_per_model_pack() -> None:
    image_bytes = _tiny_jpeg_bytes()
    detect_faces(
        image_bytes,
        model_pack=ModelPack.BUFFALO_SC,
        provider_preference=ExecutionProviderPreference.CPU,
        model_cache_dir=CACHE_DIR,
    )
    detect_faces(
        image_bytes,
        model_pack=ModelPack.BUFFALO_L,
        provider_preference=ExecutionProviderPreference.CPU,
        model_cache_dir=CACHE_DIR,
    )
    assert len(FakeFaceAnalysis.instances) == 2


def test_detect_faces_uses_gpu_ctx_id_when_cuda_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        recognition.onnxruntime,
        "get_available_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    detect_faces(
        _tiny_jpeg_bytes(),
        model_pack=ModelPack.BUFFALO_SC,
        provider_preference=ExecutionProviderPreference.AUTO,
        model_cache_dir=CACHE_DIR,
    )
    engine = FakeFaceAnalysis.instances[0]
    assert engine.prepare_calls[0]["ctx_id"] == 0


# ----------------------------------------------------------- cosine_similarity


def test_cosine_similarity_identical_vectors_is_one() -> None:
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors_is_negative_one() -> None:
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector_is_zero_not_a_division_error() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# ----------------------------------------------------------------- best_match


def test_best_match_returns_none_when_no_candidates() -> None:
    assert best_match([1.0, 0.0], [], threshold=0.5) is None


def test_best_match_returns_none_when_nobody_clears_threshold() -> None:
    candidates = [(uuid.uuid4(), [0.0, 1.0])]
    assert best_match([1.0, 0.0], candidates, threshold=0.5) is None


def test_best_match_picks_the_highest_scoring_candidate_above_threshold() -> None:
    close_person = uuid.uuid4()
    far_person = uuid.uuid4()
    candidates = [
        (far_person, [0.6, 0.4]),
        (close_person, [1.0, 0.0]),
    ]
    match = best_match([1.0, 0.0], candidates, threshold=0.5)
    assert match is not None
    assert match.person_id == close_person
    assert match.score == pytest.approx(1.0)


def test_best_match_includes_a_candidate_exactly_at_threshold() -> None:
    person = uuid.uuid4()
    match = best_match([1.0, 0.0], [(person, [1.0, 0.0])], threshold=1.0)
    assert match is not None
    assert match.person_id == person
