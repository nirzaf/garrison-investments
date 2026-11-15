"""Create the first Managing Director in an empty portal database."""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path
from uuid import UUID

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.database import AsyncSessionLocal, engine
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException
from app.utils.permissions import ROLE_MANAGING_DIRECTOR
from app.utils.security import hash_password, validate_password_policy


async def create_first_admin(
    session: AsyncSession, *, email: str, full_name: str, password: str
) -> UUID:
    email = TypeAdapter(EmailStr).validate_python(email).lower()
    full_name = full_name.strip()
    if not 2 <= len(full_name) <= 255:
        raise ValueError("Enter a full name between 2 and 255 characters.")
    validate_password_policy(password)

    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtext("garrison.bootstrap_admin")))
    )
    if await session.scalar(select(User.id).limit(1)) is not None:
        raise ValueError("Managing Director setup requires an empty user table.")

    user = User(
        email=email,
        full_name=full_name,
        role=ROLE_MANAGING_DIRECTOR,
        password_hash=hash_password(password),
        must_change_password=True,
    )
    await UserRepository(session).add(user)
    await AuditService(session).record(
        action="users.first_managing_director_created",
        user_id=user.id,
        entity_type="users",
        entity_id=user.id,
        new_values={"role": ROLE_MANAGING_DIRECTOR},
    )
    await session.commit()
    return user.id


async def run(email: str, full_name: str, password: str) -> UUID:
    try:
        async with AsyncSessionLocal() as session:
            return await create_first_admin(
                session, email=email, full_name=full_name, password=password
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error("Run this command in an interactive terminal to enter the password securely.")
    password = getpass.getpass("Temporary password: ")
    if password != getpass.getpass("Confirm temporary password: "):
        parser.error("The passwords differ.")
    try:
        user_id = asyncio.run(run(args.email, args.full_name, password))
    except ValidationError:
        parser.error("Enter a valid email address.")
    except ValueError as exc:
        parser.error(str(exc))
    except AppException as exc:
        parser.error(str(exc))
    print(f"Created first Managing Director {user_id}.")


if __name__ == "__main__":
    main()
