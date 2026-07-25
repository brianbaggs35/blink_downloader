"""One-off admin CLI tasks, run inside the backend container.

`create-admin` exists as a recovery path alongside the web setup wizard
(`POST /api/setup`, which only ever runs once — before any user exists).
There is no default/documented password anywhere: every admin account is
either created through the wizard or through this command, always with a
credential the operator chooses themselves. Usage: `make create-admin`
(wraps `python -m app.cli create-admin`).
"""

import argparse
import asyncio
import getpass
import sys

from fastapi_users import exceptions
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from app.config import get_settings
from app.db import build_engine, build_sessionmaker
from app.logs import configure_logging, get_logger
from app.users.manager import UserManager
from app.users.models import User
from app.users.schemas import UserCreate, UserUpdate

logger = get_logger(__name__)


def prompt_credentials(email: str | None, password: str | None) -> tuple[str, str]:
    if not email:
        email = input("Admin email: ").strip()
    if not password:
        password = getpass.getpass("Admin password (min 12 characters): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords did not match.", file=sys.stderr)
            raise SystemExit(1)
    return email, password


async def create_admin(email: str, password: str, display_name: str) -> None:
    settings = get_settings()
    configure_logging(settings)
    engine = build_engine(settings.database_url)
    try:
        sessionmaker = build_sessionmaker(engine)
        async with sessionmaker() as session:
            manager = UserManager(SQLAlchemyUserDatabase(session, User))
            try:
                existing = await manager.get_by_email(email)
            except exceptions.UserNotExists:
                try:
                    user = await manager.create(
                        UserCreate(
                            email=email,
                            password=password,
                            display_name=display_name,
                            is_superuser=True,
                            is_verified=True,
                        ),
                        safe=False,
                    )
                except exceptions.InvalidPasswordException as exc:
                    print(f"Password rejected: {exc.reason}", file=sys.stderr)
                    raise SystemExit(1) from exc
                print(f"Created admin account: {user.email}")
                return

            try:
                await manager.update(
                    UserUpdate(
                        password=password, is_superuser=True, is_verified=True, is_active=True
                    ),
                    existing,
                    safe=False,
                )
            except exceptions.InvalidPasswordException as exc:
                print(f"Password rejected: {exc.reason}", file=sys.stderr)
                raise SystemExit(1) from exc
            print(f"Updated existing account to admin with a new password: {existing.email}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser(
        "create-admin",
        help="Create an admin account, or reset an existing account's password to admin.",
    )
    create.add_argument("--email")
    create.add_argument("--password")
    create.add_argument("--display-name", default="Admin")

    # Only one subcommand is registered (and it's required), so argparse
    # itself guarantees args.command == "create-admin" whenever parsing
    # succeeds at all.
    args = parser.parse_args()
    email, password = prompt_credentials(args.email, args.password)
    asyncio.run(create_admin(email, password, args.display_name))


if __name__ == "__main__":
    main()
