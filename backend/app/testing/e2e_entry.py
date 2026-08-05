"""Boot sequence for the e2e backend container.

The production image is distroless (no shell), so migrate -> seed -> serve is
chained here in Python instead of `sh -c`. Run with:
``python -m app.testing.e2e_entry``
"""

import asyncio
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from app.config import get_settings
from app.testing.seed import seed, warm_up_biometrics_model

BACKEND_DIR = Path(__file__).resolve().parents[2]

UVICORN_ARGV = [
    sys.executable,
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    "0.0.0.0",  # container-internal bind behind nginx  # noqa: S104 # nosec B104
    "--port",
    "8000",
    "--proxy-headers",
    "--forwarded-allow-ips",
    "*",
]


def main() -> None:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")
    # See Settings.skip_seed: only the onboarding profile sets this, so its
    # database stays genuinely empty and /setup's one-shot gate stays open.
    if not get_settings().skip_seed:
        asyncio.run(seed())
    # Blocking here (rather than after uvicorn starts) means the container's
    # healthcheck - and so every other e2e-profile service that waits on
    # `condition: service_healthy` - doesn't go green until this is done,
    # which is what actually keeps Playwright from racing the cold load.
    asyncio.run(warm_up_biometrics_model())
    os.execv(sys.executable, UVICORN_ARGV)  # replaces PID 1, no shell  # noqa: S606 # nosec B606


if __name__ == "__main__":
    main()
