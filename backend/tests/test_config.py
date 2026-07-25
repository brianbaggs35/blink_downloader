"""Settings behavior: secret handling per environment, log-format defaults."""

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.security.crypto import SecretBox
from tests.conftest import PlainSettings


def _clear_blink_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in list(os.environ):
        if key.startswith("BLINK_"):
            monkeypatch.delenv(key)


def test_development_generates_ephemeral_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_blink_env(monkeypatch)
    settings = PlainSettings()
    assert settings.environment == "development"
    assert settings.secret_key
    # The generated encryption key must be a usable Fernet key.
    box = SecretBox(settings.encryption_key)
    assert box.decrypt(box.encrypt("hello")) == "hello"


def test_production_requires_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_blink_env(monkeypatch)
    monkeypatch.setenv("BLINK_ENVIRONMENT", "production")
    with pytest.raises(ValidationError, match="BLINK_SECRET_KEY, BLINK_ENCRYPTION_KEY"):
        PlainSettings()


def test_production_with_secrets_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_blink_env(monkeypatch)
    monkeypatch.setenv("BLINK_ENVIRONMENT", "production")
    monkeypatch.setenv("BLINK_SECRET_KEY", "x" * 43)
    monkeypatch.setenv("BLINK_ENCRYPTION_KEY", "iRZbYNDbXbGGoHy4JV2XChcPYDbdCTC9YXf29CQzB1I=")
    settings = PlainSettings()
    assert settings.render_json_logs is True


def test_render_json_logs_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_blink_env(monkeypatch)
    assert PlainSettings(log_json=True).render_json_logs is True
    assert PlainSettings(log_json=False).render_json_logs is False
    assert PlainSettings().render_json_logs is False


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    first = get_settings()
    assert get_settings() is first
    get_settings.cache_clear()
