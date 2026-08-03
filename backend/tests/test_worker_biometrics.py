"""download_biometrics_model_job: the worker entrypoint that resolves the
biometrics settings singleton and delegates to app.biometrics.service,
translating a ModelLoadError into model_download_status/model_download_error
- same shape as test_worker_sync_module.py's refresh job tests.
"""

from typing import Any

import pytest

import app.biometrics.service as biometrics_service
from app.biometrics.models import ModelDownloadStatus, ModelPack
from app.biometrics.recognition import ModelLoadError
from app.biometrics.service import get_biometrics_settings
from app.worker.tasks.biometrics import download_biometrics_model_job


async def test_download_job_succeeds_and_marks_ready(
    worker_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_ensure_model_ready(*_args: object, **_kwargs: object) -> list[str]:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    monkeypatch.setattr(biometrics_service, "ensure_model_ready", _fake_ensure_model_ready)

    async with worker_ctx["sessionmaker"]() as session:
        row = await get_biometrics_settings(session)
        row.model_download_status = ModelDownloadStatus.DOWNLOADING
        await session.commit()

    result = await download_biometrics_model_job(worker_ctx)
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        refreshed = await get_biometrics_settings(session)
        assert refreshed.model_download_status is ModelDownloadStatus.READY
        assert refreshed.model_download_providers == [
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
        assert refreshed.model_download_error is None


async def test_download_job_reports_failure_and_sets_error_status(
    worker_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> list[str]:
        raise ModelLoadError("could not reach insightface's release assets")

    monkeypatch.setattr(biometrics_service, "ensure_model_ready", _boom)

    async with worker_ctx["sessionmaker"]() as session:
        row = await get_biometrics_settings(session)
        row.model_download_status = ModelDownloadStatus.DOWNLOADING
        await session.commit()

    result = await download_biometrics_model_job(worker_ctx)
    assert result == "failed: could not reach insightface's release assets"

    async with worker_ctx["sessionmaker"]() as session:
        refreshed = await get_biometrics_settings(session)
        assert refreshed.model_download_status is ModelDownloadStatus.ERROR
        assert refreshed.model_download_error == "could not reach insightface's release assets"


async def test_download_job_uses_the_configured_model_pack(
    worker_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_packs: list[ModelPack] = []

    def _fake_ensure_model_ready(
        model_pack: ModelPack, *_args: object, **_kwargs: object
    ) -> list[str]:
        seen_packs.append(model_pack)
        return ["CPUExecutionProvider"]

    monkeypatch.setattr(biometrics_service, "ensure_model_ready", _fake_ensure_model_ready)

    async with worker_ctx["sessionmaker"]() as session:
        row = await get_biometrics_settings(session)
        row.model_pack = ModelPack.BUFFALO_SC
        await session.commit()

    await download_biometrics_model_job(worker_ctx)
    assert seen_packs == [ModelPack.BUFFALO_SC]
