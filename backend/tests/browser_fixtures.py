"""Start the isolated browser-test API or seed an account and project for one test."""

import argparse
import asyncio
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import uvicorn
from sqlalchemy.engine import make_url

from tests.password_fixtures import hash_fixture_password


def configure() -> None:
    database_url = os.environ.get(
        "BROWSER_TEST_DATABASE_URL",
        "postgresql+asyncpg://garrison:garrison_dev_password@127.0.0.1:5432/garrison_browser_test",
    )
    url = make_url(database_url)
    name = url.database or ""
    if url.host not in {"localhost", "127.0.0.1"} or not (
        name == "garrison_browser_test" or name.startswith("garrison_browser_test_")
    ):
        raise ValueError("Browser tests require a dedicated local garrison_browser_test database.")
    redis_url = os.environ.get("BROWSER_TEST_REDIS_URL", "redis://127.0.0.1:6379/8")
    s3_endpoint = os.environ.get("BROWSER_TEST_MINIO_ENDPOINT", "127.0.0.1:9000")
    if urlsplit(redis_url).hostname not in {"localhost", "127.0.0.1"} or urlsplit(
        f"http://{s3_endpoint}"
    ).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Browser tests require local Redis and object storage.")
    os.environ.update(
        APP_ENV="test",
        DATABASE_URL=database_url,
        REDIS_URL=redis_url,
        DEV_EXPOSE_OTP="true",
        AUTH_RATE_LIMIT_MAX_REQUESTS="60",
        EXCEPTION_EMAIL_ENABLED="false",
        LOG_LEVEL="WARNING",
        FRONTEND_BASE_URL="http://127.0.0.1:4325",
        SMTP_HOST="127.0.0.1",
        SMTP_PORT="1",
        USESEND_API_URL="http://127.0.0.1:1",
        USESEND_API_KEY="",
        MINIO_ENDPOINT=s3_endpoint,
        MINIO_BUCKET="garrison-browser-test",
        MINIO_SECURE="false",
        MINIO_PUBLIC_ENDPOINT=s3_endpoint,
        MINIO_PUBLIC_SECURE="false",
    )


async def seed(role: str, existing_project_id: UUID | None) -> None:
    from app.database import AsyncSessionLocal, engine
    from app.models.project import Project
    from app.models.project_member import ProjectMember
    from app.models.user import User
    from app.utils.time import business_today

    identifier = uuid4().hex[:12]
    email = f"browser-{identifier}@example.com"
    password = secrets.token_urlsafe(24)
    try:
        async with AsyncSessionLocal() as session:
            user = User(
                email=email,
                full_name=f"Browser Test {role.replace('_', ' ').title()}",
                role=role,
                employee_code=f"E2E-{identifier}",
                password_hash=hash_fixture_password(password),
                must_change_password=False,
            )
            session.add(user)
            await session.flush()
            if existing_project_id is not None:
                project = await session.get(Project, existing_project_id)
                if project is None:
                    raise ValueError("The browser-test project does not exist.")
            else:
                project = Project(
                    name=f"Browser Test {identifier}",
                    code=f"E2E-{identifier}",
                    status="active",
                    scope_of_work="Browser regression tests",
                    target_end_date=business_today() + timedelta(days=60),
                    created_by=user.id,
                )
                session.add(project)
                await session.flush()
            if role == "civil_supervisor":
                session.add(ProjectMember(project_id=project.id, user_id=user.id))
            if role == "project_manager" and existing_project_id is not None:
                session.add(
                    ProjectMember(
                        project_id=project.id, user_id=user.id, role_in_project="project_manager"
                    )
                )
            project_id = str(project.id)
            await session.commit()
    finally:
        await engine.dispose()
    print(json.dumps({"email": email, "password": password, "projectId": project_id}))


async def expire_login_challenge(challenge_id: UUID) -> None:
    from app.database import AsyncSessionLocal, engine
    from app.models.auth import AuthOtpChallenge
    from app.models.user import User

    try:
        async with AsyncSessionLocal() as session:
            challenge = await session.get(AuthOtpChallenge, challenge_id)
            user = await session.get(User, challenge.user_id) if challenge else None
            if (
                not challenge
                or challenge.purpose != "login"
                or challenge.consumed_at is not None
                or not user
                or not user.email.startswith("browser-")
                or not user.email.endswith("@example.com")
            ):
                raise ValueError("Expected an unconsumed browser fixture login challenge.")
            challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    from app.utils.permissions import VALID_ROLES

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["seed", "seed-supervisor", "serve", "expire-login"])
    parser.add_argument("--role", choices=sorted(VALID_ROLES), default="admin")
    parser.add_argument("--project-id", type=UUID)
    parser.add_argument("--challenge-id", type=UUID)
    args = parser.parse_args()
    if args.command == "expire-login" and args.challenge_id is None:
        parser.error("expire-login requires --challenge-id")
    configure()
    if args.command == "serve":
        uvicorn.run("app.main:app", host="127.0.0.1", port=8425, access_log=False)
    elif args.command == "expire-login":
        asyncio.run(expire_login_challenge(args.challenge_id))
    else:
        asyncio.run(
            seed(
                "civil_supervisor" if args.command == "seed-supervisor" else args.role,
                args.project_id,
            )
        )
