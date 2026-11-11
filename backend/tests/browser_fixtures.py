"""Start the isolated browser-test API or seed an account and project for one test."""

import argparse
import asyncio
import json
import os
import secrets
from datetime import timedelta
from uuid import uuid4

import uvicorn
from sqlalchemy.engine import make_url


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
    os.environ.update(
        APP_ENV="test",
        DATABASE_URL=database_url,
        REDIS_URL="redis://127.0.0.1:6379/8",
        DEV_EXPOSE_OTP="true",
        AUTH_RATE_LIMIT_MAX_REQUESTS="60",
        EXCEPTION_EMAIL_ENABLED="false",
        LOG_LEVEL="WARNING",
        SMTP_HOST="127.0.0.1",
        SMTP_PORT="1",
        USESEND_API_URL="http://127.0.0.1:1",
        USESEND_API_KEY="",
        MINIO_ENDPOINT="127.0.0.1:9000",
        MINIO_BUCKET="garrison-browser-test",
        MINIO_SECURE="false",
    )


async def seed() -> None:
    from app.database import AsyncSessionLocal, engine
    from app.models.project import Project
    from app.models.user import User
    from app.utils.security import hash_password
    from app.utils.time import business_today

    identifier = uuid4().hex[:12]
    email = f"browser-{identifier}@example.com"
    password = secrets.token_urlsafe(24)
    try:
        async with AsyncSessionLocal() as session:
            user = User(
                email=email,
                full_name="Browser Test Admin",
                role="admin",
                employee_code=f"E2E-{identifier}",
                password_hash=hash_password(password),
                must_change_password=False,
            )
            session.add(user)
            await session.flush()
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
            project_id = str(project.id)
            await session.commit()
    finally:
        await engine.dispose()
    print(json.dumps({"email": email, "password": password, "projectId": project_id}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["seed", "serve"])
    args = parser.parse_args()
    configure()
    if args.command == "serve":
        uvicorn.run("app.main:app", host="127.0.0.1", port=8425, access_log=False)
    else:
        asyncio.run(seed())
