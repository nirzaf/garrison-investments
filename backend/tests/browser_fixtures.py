"""Start the isolated browser-test API or seed an account and project for one test."""

import argparse
import asyncio
import json
import os
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
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
        HR_LINE_MANAGER_REVIEW_ENABLED="true",
        HR_SELF_TIME_SUBMISSION_ENABLED="true",
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
            if role == "site_supervisor":
                session.add(ProjectMember(project_id=project.id, user_id=user.id))
            if role == "group_project_manager" and existing_project_id is not None:
                session.add(
                    ProjectMember(
                        project_id=project.id,
                        user_id=user.id,
                        role_in_project="group_project_manager",
                    )
                )
            project_id = str(project.id)
            project_code = project.code
            await session.commit()
    finally:
        await engine.dispose()
    print(
        json.dumps(
            {
                "email": email,
                "password": password,
                "projectId": project_id,
                "projectCode": project_code,
            }
        )
    )


async def seed_delegation() -> None:
    from app.database import AsyncSessionLocal, engine
    from app.models.approval import Approval
    from app.models.inventory import (
        InventoryItem,
        MaterialRequest,
        MaterialRequestLine,
        StorageLocation,
    )
    from app.models.project import Project
    from app.models.user import User
    from app.utils.security import hash_password, utc_now
    from app.utils.time import business_today

    identifier = uuid4().hex[:12]
    email = f"browser-delegator-{identifier}@example.com"
    password = secrets.token_urlsafe(24)
    title = f"Browser delegation {identifier}"
    candidate_name = "Browser Candidate 060"
    try:
        async with AsyncSessionLocal() as session:
            actor = User(
                email=email,
                full_name=f"Browser Test Operations Director {identifier}",
                role="operations_director",
                employee_code=f"E2E-{identifier}",
                password_hash=hash_password(password),
                must_change_password=False,
            )
            submitter = User(
                email=f"browser-submitter-{identifier}@example.com",
                full_name=f"Browser Submitter {identifier}",
                role="quantity_surveyor",
                employee_code=f"E2E-SUB-{identifier}",
                password_hash=hash_password(secrets.token_urlsafe(24)),
                must_change_password=False,
            )
            candidates = [
                User(
                    email=f"browser-candidate-{identifier}-{index:03d}@example.com",
                    full_name=f"Browser Candidate {index:03d}",
                    role="managing_director",
                    employee_code=f"E2E-CAN-{identifier}-{index:03d}",
                    password_hash=hash_password(secrets.token_urlsafe(24)),
                    must_change_password=False,
                )
                for index in range(61)
            ]
            project = Project(
                name=f"Browser Delegation {identifier}",
                code=f"BD-{identifier}",
                status="active",
                scope_of_work="Browser delegation search regression",
                target_end_date=business_today() + timedelta(days=30),
                created_by=actor.id,
            )
            session.add_all([actor, submitter, *candidates, project])
            await session.flush()
            location = StorageLocation(
                name=f"Browser Store {identifier}",
                code=f"BS-{identifier}",
                location_type="project_site",
                project_id=project.id,
            )
            item = InventoryItem(
                name=f"Browser item {identifier}",
                item_code=f"BI-{identifier}",
                category="Browser test",
                item_type="consumable",
                unit="each",
            )
            session.add_all([location, item])
            await session.flush()
            request = MaterialRequest(
                request_number=f"BR-{identifier}",
                project_id=project.id,
                requester_id=submitter.id,
                from_location_id=location.id,
                status="requested",
                notes="Disposable browser-test approval.",
            )
            session.add(request)
            await session.flush()
            approval = Approval(
                request_type="material_request",
                request_id=request.id,
                project_id=project.id,
                submitter_id=submitter.id,
                approver_id=actor.id,
                status="pending",
                title=title,
                submitted_at=utc_now(),
                due_at=utc_now() + timedelta(days=1),
            )
            session.add_all(
                [
                    MaterialRequestLine(
                        request_id=request.id,
                        item_id=item.id,
                        quantity=Decimal("1.000"),
                    ),
                    approval,
                ]
            )
            await session.flush()
            await session.commit()
    finally:
        await engine.dispose()
    print(
        json.dumps(
            {
                "email": email,
                "password": password,
                "approvalId": str(approval.id),
                "approvalTitle": title,
                "candidateId": str(candidates[60].id),
                "candidateName": candidate_name,
            }
        )
    )


async def seed_analytics_finance(project_id: UUID) -> None:
    """Create read-only finance facts for analytics browser coverage."""
    from app.database import AsyncSessionLocal, engine
    from app.models.finance import Invoice, Payment
    from app.models.project import Project
    from app.utils.security import utc_now

    try:
        async with AsyncSessionLocal() as session:
            project = await session.get(Project, project_id)
            if project is None or project.created_by is None:
                raise ValueError("The analytics browser-test project is unavailable.")
            first = Invoice(
                invoice_number=f"AN-{project_id.hex[:8]}-1",
                project_id=project.id,
                invoice_date=date(2024, 1, 1),
                due_date=date(2024, 1, 31),
                amount=Decimal("100.00"),
                tax_amount=Decimal("7.25"),
                total_amount=Decimal("107.25"),
                status="approved",
                payment_status="partial",
                created_by=project.created_by,
                approved_by=project.created_by,
                approved_at=utc_now(),
            )
            second = Invoice(
                invoice_number=f"AN-{project_id.hex[:8]}-2",
                project_id=project.id,
                invoice_date=date(2024, 1, 1),
                due_date=date(2024, 1, 31),
                amount=Decimal("100.00"),
                tax_amount=Decimal("7.25"),
                total_amount=Decimal("107.25"),
                status="approved",
                payment_status="unpaid",
                created_by=project.created_by,
                approved_by=project.created_by,
                approved_at=utc_now(),
            )
            session.add_all([first, second])
            await session.flush()
            session.add(
                Payment(
                    invoice_id=first.id,
                    payment_date=date(2024, 1, 15),
                    amount=Decimal("42.15"),
                    method="browser test fixture",
                    recorded_by=project.created_by,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
    print(json.dumps({"seeded": True, "projectId": str(project_id)}))


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


async def seed_employee_payslip(employee_id: UUID, maker_id: UUID, reviewer_id: UUID) -> None:
    # This key belongs only to the Playwright run and is shared by its API and fixture process.
    os.environ["HR_ENCRYPTION_KEY"] = os.environ["BROWSER_TEST_HR_ENCRYPTION_KEY"]
    from app.database import AsyncSessionLocal, engine
    from app.models.hr import HrEmployee
    from app.models.user import User
    from app.schemas.hr import (
        CompensationTermCreateRequest,
        PayrollPeriodCreateRequest,
        PayrollPolicyCreateRequest,
        PayrollRunCreateRequest,
    )
    from app.services.hr_payroll_snapshot import (
        approve_payroll_snapshot,
        calculate_payroll_snapshot,
        publish_payslips,
    )
    from app.services.hr_service import HrService
    from app.utils.permissions import (
        PERMISSION_HR_PAYROLL_APPROVE,
        PERMISSION_HR_PAYROLL_PREPARE,
        PERMISSION_HR_PAYROLL_SENSITIVE,
        ROLE_PERMISSIONS,
    )

    try:
        async with AsyncSessionLocal() as session:
            employee = await session.get(HrEmployee, employee_id)
            maker = await session.get(User, maker_id)
            reviewer = await session.get(User, reviewer_id)
            recipient = (
                await session.get(User, employee.user_id) if employee and employee.user_id else None
            )
            if (
                employee is None
                or maker is None
                or reviewer is None
                or recipient is None
                or len({maker.id, reviewer.id, recipient.id}) != 3
                or maker.role != "hr_manager"
                or reviewer.role != "hr_manager"
                or not all(
                    user.email.startswith("browser-") and user.email.endswith("@example.com")
                    for user in (maker, reviewer, recipient)
                )
            ):
                raise ValueError("Expected three distinct browser fixture accounts.")
            # Scoped to this short-lived test process. The API retains its standard role grants.
            ROLE_PERMISSIONS["hr_manager"] |= {
                PERMISSION_HR_PAYROLL_PREPARE,
                PERMISSION_HR_PAYROLL_APPROVE,
                PERMISSION_HR_PAYROLL_SENSITIVE,
            }
            service = HrService(session)
            await service.create_compensation_term(
                CompensationTermCreateRequest(
                    employee_id=employee.id,
                    effective_from=date(2025, 1, 1),
                    base_salary="100.05",
                    currency="LKR",
                ),
                maker,
            )
            period = await service.create_payroll_period(
                PayrollPeriodCreateRequest(
                    period_code="Synthetic Chrome payroll",
                    period_start=date(2025, 1, 1),
                    period_end=date(2025, 1, 31),
                    pay_date=date(2025, 2, 1),
                ),
                maker,
            )
            policy = await service.create_payroll_policy(
                PayrollPolicyCreateRequest(
                    code=f"CHROME-PAY-{employee.id.hex[:8]}",
                    name="Synthetic Chrome policy",
                    rules_json={
                        "calculation_basis": "base_salary_only",
                        "currency": "LKR",
                        "rounding": "half_up",
                        "pay_frequency": "monthly",
                        "employee_deduction_rate": "0.10",
                    },
                ),
                maker,
            )
            await service.approve_payroll_policy(policy.id, reviewer)
            draft = await service.create_payroll_run(
                PayrollRunCreateRequest(payroll_period_id=period.id, policy_id=policy.id), maker
            )
            run = await calculate_payroll_snapshot(session, draft.id, [employee.id], maker)
            digest = run.snapshot_digest
            assert digest is not None
            await approve_payroll_snapshot(session, run.id, digest, reviewer)
            await publish_payslips(session, run.id, digest, reviewer)
            print(json.dumps({"runId": str(run.id)}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    from app.utils.permissions import VALID_ROLES

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "seed",
            "seed-supervisor",
            "seed-delegation",
            "seed-analytics-finance",
            "seed-employee-payslip",
            "serve",
            "expire-login",
        ],
    )
    parser.add_argument("--role", choices=sorted(VALID_ROLES), default="managing_director")
    parser.add_argument("--project-id", type=UUID)
    parser.add_argument("--challenge-id", type=UUID)
    parser.add_argument("--employee-id", type=UUID)
    parser.add_argument("--maker-id", type=UUID)
    parser.add_argument("--reviewer-id", type=UUID)
    args = parser.parse_args()
    if args.command == "expire-login" and args.challenge_id is None:
        parser.error("expire-login requires --challenge-id")
    if args.command == "seed-analytics-finance" and args.project_id is None:
        parser.error("seed-analytics-finance requires --project-id")
    configure()
    if args.command == "serve":
        uvicorn.run("app.main:app", host="127.0.0.1", port=8425, access_log=False)
    elif args.command == "expire-login":
        asyncio.run(expire_login_challenge(args.challenge_id))
    elif args.command == "seed-delegation":
        asyncio.run(seed_delegation())
    elif args.command == "seed-employee-payslip":
        if not (args.employee_id and args.maker_id and args.reviewer_id):
            parser.error("seed-employee-payslip needs employee, maker and reviewer IDs")
        asyncio.run(seed_employee_payslip(args.employee_id, args.maker_id, args.reviewer_id))
    elif args.command == "seed-analytics-finance":
        asyncio.run(seed_analytics_finance(args.project_id))
    else:
        asyncio.run(
            seed(
                "site_supervisor" if args.command == "seed-supervisor" else args.role,
                args.project_id,
            )
        )
