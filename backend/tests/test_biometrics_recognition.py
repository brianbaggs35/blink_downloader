"""app/biometrics/recognition.py: insightface faked at the FaceAnalysis
class boundary, since constructing a real one triggers a model download —
never a real network call, matching the blinkpy/AI-provider convention used
elsewhere in this project.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false
# White-box: clears the private engine cache between tests for isolation.
# pyright: reportPrivateUsage=false

import subprocess
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
    _gpu_actually_usable,
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
    # _gpu_actually_usable is process-lifetime-cached by design (see its own
    # docstring) - a real problem for test isolation, since one test's
    # result would otherwise leak into every test after it.
    _gpu_actually_usable.cache_clear()


# ---------------------------------------------------------- available_providers


def test_available_providers_reflects_onnxruntime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        recognition.onnxruntime, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    assert available_providers() == ["CPUExecutionProvider"]


def test_available_providers_includes_cuda_when_a_real_gpu_is_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recognition.onnxruntime,
        "get_available_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    monkeypatch.setattr(recognition, "_gpu_actually_usable", lambda: True)
    assert available_providers() == ["CUDAExecutionProvider", "CPUExecutionProvider"]


def test_available_providers_hides_cuda_when_compiled_in_but_not_actually_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise this panel would confidently claim "GPU available" on a
    container with no device passthrough configured, on a host that may
    well have a real GPU sitting right there unreachable - see
    resolve_providers' own equivalent gating for the full reasoning."""
    monkeypatch.setattr(
        recognition.onnxruntime,
        "get_available_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    monkeypatch.setattr(recognition, "_gpu_actually_usable", lambda: False)
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


def test_resolve_providers_auto_prefers_cuda_when_a_real_gpu_is_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recognition.onnxruntime,
        "get_available_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    monkeypatch.setattr(recognition, "_gpu_actually_usable", lambda: True)
    assert resolve_providers(ExecutionProviderPreference.AUTO) == [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]


def test_resolve_providers_auto_falls_back_to_cpu_when_cuda_compiled_in_but_no_real_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """onnxruntime-gpu always reports CUDAExecutionProvider as available -
    that's a build-time fact, not proof this host can actually use it."""
    monkeypatch.setattr(
        recognition.onnxruntime,
        "get_available_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    monkeypatch.setattr(recognition, "_gpu_actually_usable", lambda: False)
    assert resolve_providers(ExecutionProviderPreference.AUTO) == ["CPUExecutionProvider"]


# ------------------------------------------------------- _gpu_actually_usable


def _no_nvidia_smi(_name: str) -> str | None:
    return None


def _has_nvidia_smi(_name: str) -> str | None:
    return "/usr/bin/nvidia-smi"


def _run_returns(returncode: int) -> Any:
    def _run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args=[], returncode=returncode)

    return _run


def _run_raises_oserror(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
    raise OSError("exec format error")


def test_gpu_actually_usable_is_false_when_nvidia_smi_is_not_on_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recognition.shutil, "which", _no_nvidia_smi)
    assert _gpu_actually_usable() is False


def test_gpu_actually_usable_is_true_when_nvidia_smi_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recognition.shutil, "which", _has_nvidia_smi)
    monkeypatch.setattr(recognition.subprocess, "run", _run_returns(0))
    assert _gpu_actually_usable() is True


def test_gpu_actually_usable_is_false_when_nvidia_smi_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plain (non--gpu) compose files inject no device reservation, so
    a present-but-non-functional nvidia-smi (no accessible device) is a
    real, reachable state, not just a hypothetical."""
    monkeypatch.setattr(recognition.shutil, "which", _has_nvidia_smi)
    monkeypatch.setattr(recognition.subprocess, "run", _run_returns(1))
    assert _gpu_actually_usable() is False


def test_gpu_actually_usable_is_false_when_nvidia_smi_cannot_even_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recognition.shutil, "which", _has_nvidia_smi)
    monkeypatch.setattr(recognition.subprocess, "run", _run_raises_oserror)
    assert _gpu_actually_usable() is False


def test_gpu_actually_usable_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def _which(_name: str) -> str | None:
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(recognition.shutil, "which", _which)
    assert _gpu_actually_usable() is False
    assert _gpu_actually_usable() is False
    assert calls == 1


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
    monkeypatch.setattr(recognition, "_gpu_actually_usable", lambda: True)
    detect_faces(
        _tiny_jpeg_bytes(),
        model_pack=ModelPack.BUFFALO_SC,
        provider_preference=ExecutionProviderPreference.AUTO,
        model_cache_dir=CACHE_DIR,
    )
    engine = FakeFaceAnalysis.instances[0]
    assert engine.prepare_calls[0]["ctx_id"] == 0


# ------------------------------------------------------------- ModelLoadError


def test_get_engine_wraps_construction_failure_in_model_load_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*, name: str, root: str, providers: list[str]) -> FakeFaceAnalysis:
        raise RuntimeError("could not reach github release assets")

    monkeypatch.setattr(recognition, "FaceAnalysis", _boom)
    with pytest.raises(recognition.ModelLoadError, match="buffalo_sc"):
        detect_faces(
            _tiny_jpeg_bytes(),
            model_pack=ModelPack.BUFFALO_SC,
            provider_preference=ExecutionProviderPreference.CPU,
            model_cache_dir=CACHE_DIR,
        )
    assert FakeFaceAnalysis.instances == []


def test_get_engine_failure_does_not_poison_the_cache_for_a_later_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*, name: str, root: str, providers: list[str]) -> FakeFaceAnalysis:
        raise RuntimeError("network blip")

    monkeypatch.setattr(recognition, "FaceAnalysis", _boom)
    with pytest.raises(recognition.ModelLoadError):
        detect_faces(
            _tiny_jpeg_bytes(),
            model_pack=ModelPack.BUFFALO_SC,
            provider_preference=ExecutionProviderPreference.CPU,
            model_cache_dir=CACHE_DIR,
        )

    monkeypatch.setattr(recognition, "FaceAnalysis", FakeFaceAnalysis)
    detect_faces(
        _tiny_jpeg_bytes(),
        model_pack=ModelPack.BUFFALO_SC,
        provider_preference=ExecutionProviderPreference.CPU,
        model_cache_dir=CACHE_DIR,
    )
    assert len(FakeFaceAnalysis.instances) == 1


# --------------------------------------------------------- ensure_model_ready


def test_ensure_model_ready_loads_the_engine_and_returns_providers() -> None:
    providers = recognition.ensure_model_ready(
        ModelPack.BUFFALO_L, ExecutionProviderPreference.CPU, CACHE_DIR
    )
    assert providers == ["CPUExecutionProvider"]
    assert len(FakeFaceAnalysis.instances) == 1


def test_ensure_model_ready_raises_model_load_error_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*, name: str, root: str, providers: list[str]) -> FakeFaceAnalysis:
        raise OSError("cache dir not writable")

    monkeypatch.setattr(recognition, "FaceAnalysis", _boom)
    with pytest.raises(recognition.ModelLoadError):
        recognition.ensure_model_ready(
            ModelPack.BUFFALO_L, ExecutionProviderPreference.CPU, CACHE_DIR
        )


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
    assert best_match([1.0, 0.0], [], [], threshold=0.5) is None


def test_best_match_returns_none_when_nobody_clears_threshold() -> None:
    candidates = [(uuid.uuid4(), [0.0, 1.0])]
    assert best_match([1.0, 0.0], candidates, [], threshold=0.5) is None


def test_best_match_picks_the_highest_scoring_candidate_above_threshold() -> None:
    close_person = uuid.uuid4()
    far_person = uuid.uuid4()
    candidates = [
        (far_person, [0.6, 0.4]),
        (close_person, [1.0, 0.0]),
    ]
    match = best_match([1.0, 0.0], candidates, [], threshold=0.5)
    assert match is not None
    assert match.person_id == close_person
    assert match.score == pytest.approx(1.0)


def test_best_match_includes_a_candidate_exactly_at_threshold() -> None:
    person = uuid.uuid4()
    match = best_match([1.0, 0.0], [(person, [1.0, 0.0])], [], threshold=1.0)
    assert match is not None


def test_best_match_vetoes_a_person_whose_negative_sample_is_at_least_as_close() -> None:
    person = uuid.uuid4()
    query = [1.0, 0.0]
    positives = [(person, [0.8, 0.6])]  # cosine(query, positive) == 0.8
    negatives = [(person, [1.0, 0.0])]  # cosine(query, negative) == 1.0 - the exact query face
    match = best_match(query, positives, negatives, threshold=0.5)
    assert match is None


def test_best_match_still_matches_when_negative_is_for_a_different_person() -> None:
    target = uuid.uuid4()
    other = uuid.uuid4()
    positives = [(target, [1.0, 0.0])]
    negatives = [(other, [1.0, 0.0])]
    match = best_match([1.0, 0.0], positives, negatives, threshold=0.5)
    assert match is not None
    assert match.person_id == target


def test_best_match_allows_a_positive_that_clearly_beats_its_own_negative() -> None:
    person = uuid.uuid4()
    positives = [(person, [1.0, 0.0])]
    negatives = [(person, [0.0, 1.0])]
    match = best_match([1.0, 0.0], positives, negatives, threshold=0.5)
    assert match is not None
    assert match.person_id == person


def test_best_match_keeps_the_higher_of_two_negatives_for_the_same_person() -> None:
    person = uuid.uuid4()
    query = [1.0, 0.0]
    positives = [(person, [1.0, 0.0])]
    # Two negative samples for the same person, strongest listed first - the
    # weaker one seen afterward must not overwrite it and weaken the veto.
    negatives = [(person, [1.0, 0.0]), (person, [0.0, 1.0])]
    match = best_match(query, positives, negatives, threshold=0.5)
    assert match is None


def test_best_match_keeps_scanning_past_a_positive_that_does_not_beat_the_current_best() -> None:
    best_person = uuid.uuid4()
    weaker_person = uuid.uuid4()
    query = [1.0, 0.0]
    # weaker_person is listed after best_person but scores lower - the loop
    # must not let it replace the already-found best match.
    positives = [(best_person, [1.0, 0.0]), (weaker_person, [0.8, 0.6])]
    match = best_match(query, positives, [], threshold=0.5)
    assert match is not None
    assert match.person_id == best_person
