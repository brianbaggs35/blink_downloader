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

from app.testing.seed import seed

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
    asyncio.run(seed())
    os.execv(sys.executable, UVICORN_ARGV)  # replaces PID 1, no shell  # noqa: S606 # nosec B606


if __name__ == "__main__":
    main()
