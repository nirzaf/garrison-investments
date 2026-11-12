"""Start the isolated browser-test API or seed an account and project for one test."""

import argparse
import asyncio
import json
import os
import secrets
from datetime import timedelta
from urllib.parse import urlsplit
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
    redis_url = os.environ.get("BROWSER_TEST_REDIS_URL", "redis://127.0.0.1:6379/8")
    s3_endpoint = os.environ.get("BROWSER_TEST_MINIO_ENDPOINT", "127.0.0.1:9000")
    if (
        urlsplit(redis_url).hostname not in {"localhost", "127.0.0.1"}
        or urlsplit(f"http://{s3_endpoint}").hostname not in {"localhost", "127.0.0.1"}
    ):
        raise ValueError("Browser tests require local Redis and object storage.")
    os.environ.update(
        APP_ENV="test",
        DATABASE_URL=database_url,
        REDIS_URL=redis_url,
        DEV_EXPOSE_OTP="true",
        AUTH_RATE_LIMIT_MAX_REQUESTS="60",
        EXCEPTION_EMAIL_ENABLED="false",
        LOG_LEVEL="WARNING",
        SMTP_HOST="127.0.0.1",
        SMTP_PORT="1",
        USESEND_API_URL="http://127.0.0.1:1",
        USESEND_API_KEY="",
        MINIO_ENDPOINT=s3_endpoint,
        MINIO_BUCKET="garrison-browser-test",
        MINIO_SECURE="false",
    )


async def seed(role: str) -> None:
    from app.database import AsyncSessionLocal, engine
    from app.models.project import Project
    from app.models.project_member import ProjectMember
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
                full_name=f"Browser Test {role.replace('_', ' ').title()}",
                role=role,
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
            if role == "civil_supervisor":
                session.add(ProjectMember(project_id=project.id, user_id=user.id))
            project_id = str(project.id)
            await session.commit()
    finally:
        await engine.dispose()
    print(json.dumps({"email": email, "password": password, "projectId": project_id}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["seed", "seed-supervisor", "serve"])
    parser.add_argument("--role", choices=["admin", "store_keeper"], default="admin")
    args = parser.parse_args()
    configure()
    if args.command == "serve":
        uvicorn.run("app.main:app", host="127.0.0.1", port=8425, access_log=False)
    else:
        asyncio.run(seed("civil_supervisor" if args.command == "seed-supervisor" else args.role))
