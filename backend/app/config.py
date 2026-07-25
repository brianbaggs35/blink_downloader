"""Application settings loaded from the environment (prefix ``BLINK_``)."""

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.security.crypto import generate_key

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BLINK_", env_file=".env", extra="ignore")

    environment: Environment = "development"
    database_url: str = "postgresql+asyncpg://blink:blink@localhost:55432/blink_test"
    redis_url: str = "redis://localhost:63790/0"

    # Secrets. Required in production; ephemeral values are generated for
    # development/test so a bare checkout runs without a .env file.
    secret_key: str = ""
    encryption_key: str = ""

    cookie_name: str = "blink_session"
    cookie_secure: bool = True
    session_lifetime_seconds: int = 60 * 60 * 24 * 7

    storage_dir: Path = Path("/data/clips")
    biometrics_model_cache_dir: Path = Path("/data/insightface")
    """Where insightface's detection/recognition ONNX models are downloaded
    to on first use (a few hundred MB) — its own default is a dotfile under
    the process's home directory, which isn't stable across dev-as-root vs.
    prod-as-nonroot images, so this is pinned explicitly and volume-mounted
    like storage_dir."""

    blink_sync_interval_seconds: int = 30
    blink_initial_sync_days: int = 1
    blink_auto_analyze_limit: int = 5
    """Cap on how many clips a single sync run auto-queues for AI analysis.

    A first-time connection or a reconnect after an outage can turn up many
    new clips at once; auto-analyzing all of them would burn through AI
    budget/rate limits on a backlog nobody asked to analyze. Only the N most
    recent (by recorded_at) get auto-queued — the rest still download
    normally and stay one click away via the clip modal's "Analyze now" or
    bulk-analyze. A routine sync (a handful of new clips) is never affected
    since it's already under the cap.
    """

    log_level: str = "INFO"
    log_json: bool | None = None

    @model_validator(mode="after")
    def _fill_or_require_secrets(self) -> Self:
        if self.environment == "production":
            missing = [
                name
                for name, value in (
                    ("BLINK_SECRET_KEY", self.secret_key),
                    ("BLINK_ENCRYPTION_KEY", self.encryption_key),
                )
                if not value
            ]
            if missing:
                msg = f"{', '.join(missing)} must be set in production (run `make secrets`)"
                raise ValueError(msg)
        else:
            if not self.secret_key:
                self.secret_key = secrets.token_urlsafe(32)
            if not self.encryption_key:
                self.encryption_key = generate_key()
        return self

    @property
    def render_json_logs(self) -> bool:
        if self.log_json is not None:
            return self.log_json
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
