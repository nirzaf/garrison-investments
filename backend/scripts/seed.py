import asyncio
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.boq_item import BoqItem
from app.models.daily_report import (
    DailyReport,
    ReportEquipment,
    ReportManpower,
    ReportMaterialConsumption,
)
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_milestone import ProjectMilestone
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.security import hash_password

DEFAULT_ADMIN_EMAIL = "fazrin@quadrate.lk"
DEFAULT_ADMIN_PASSWORD = "YahmikAllah@123"
DEFAULT_PASSWORD = "YahmikAllah@123"

SEED_USERS = [
    {
        "email": DEFAULT_ADMIN_EMAIL,
        "full_name": "System Administrator",
        "role": "admin",
        "employee_code": "ADMIN-001",
        "phone": "+97450000001",
        "designation": "System Administrator",
    },
    {
        "email": "gm@garrisons.qa",
        "full_name": "General Manager",
        "role": "general_manager",
        "employee_code": "GM-001",
        "phone": "+97450000002",
        "designation": "General Manager",
    },
    {
        "email": "operations@garrisons.qa",
        "full_name": "Operation Manager",
        "role": "operation_manager",
        "employee_code": "OPS-001",
        "phone": "+97450000003",
        "designation": "Operation Manager",
    },
    {
        "email": "pm@garrisons.qa",
        "full_name": "Project Manager",
        "role": "project_manager",
        "employee_code": "PM-001",
        "phone": "+97450000004",
        "designation": "Project Manager",
    },
    {
        "email": "engineer@garrisons.qa",
        "full_name": "Civil Engineer",
        "role": "civil_engineer",
        "employee_code": "ENG-001",
        "phone": "+97450000005",
        "designation": "Civil Engineer",
    },
    {
        "email": "supervisor@garrisons.qa",
        "full_name": "Civil Supervisor",
        "role": "civil_supervisor",
        "employee_code": "SUP-001",
        "phone": "+97450000006",
        "designation": "Civil Supervisor",
    },
    {
        "email": "store@garrisons.qa",
        "full_name": "Store Keeper",
        "role": "store_keeper",
        "employee_code": "STORE-001",
        "phone": "+97450000007",
        "designation": "Store Keeper",
    },
    {
        "email": "accounts@garrisons.qa",
        "full_name": "Accounts Officer",
        "role": "accounts",
        "employee_code": "ACC-001",
        "phone": "+97450000008",
        "designation": "Accounts",
    },
]

SEED_PROJECTS = [
    {
        "code": "GIP-001",
        "name": "Lusail Villa Fit-Out",
        "location": "Lusail, Qatar",
        "description": "Residential fit-out project used for launch UAT.",
        "scope_of_work": "Civil finishing, gypsum, paint, MEP coordination, and handover works.",
        "status": "active",
        "budget_amount": Decimal("950000.00"),
        "start_date": date.today() - timedelta(days=30),
        "target_end_date": date.today() + timedelta(days=90),
        "client_name": "Garrisons Demo Client",
        "contract_number": "CNT-LUSAIL-001",
        "progress_percentage": Decimal("35.00"),
        "members": [
            ("pm@garrisons.qa", "Project Manager"),
            ("engineer@garrisons.qa", "Civil Engineer"),
            ("supervisor@garrisons.qa", "Civil Supervisor"),
            ("store@garrisons.qa", "Store Keeper"),
            ("accounts@garrisons.qa", "Accounts"),
        ],
        "milestones": [
            ("Site Mobilization", "Civil", 1, Decimal("100.00"), "completed"),
            ("Blockwork And Plaster", "Civil", 2, Decimal("55.00"), "in_progress"),
            ("Final Finishes", "Civil", 3, Decimal("0.00"), "not_started"),
        ],
        "boq": [
            (
                "CIV-001",
                "Blockwork 200mm",
                "Civil",
                "Blockwork",
                "m2",
                Decimal("450.000"),
                Decimal("85.00"),
            ),
            (
                "CIV-002",
                "Internal plaster",
                "Civil",
                "Plaster",
                "m2",
                Decimal("900.000"),
                Decimal("42.00"),
            ),
            (
                "FIN-001",
                "Premium emulsion paint",
                "Finishes",
                "Painting",
                "m2",
                Decimal("1200.000"),
                Decimal("28.00"),
            ),
        ],
    },
    {
        "code": "GIP-002",
        "name": "West Bay Office Renovation",
        "location": "West Bay, Doha",
        "description": "Commercial renovation project used for approval and dashboard checks.",
        "scope_of_work": (
            "Partition changes, flooring, ceiling repairs, electrical containment, "
            "and snag closure."
        ),
        "status": "planning",
        "budget_amount": Decimal("620000.00"),
        "start_date": date.today() + timedelta(days=10),
        "target_end_date": date.today() + timedelta(days=120),
        "client_name": "Garrisons Corporate Demo",
        "contract_number": "CNT-WB-002",
        "progress_percentage": Decimal("5.00"),
        "members": [
            ("operations@garrisons.qa", "Operation Manager"),
            ("pm@garrisons.qa", "Project Manager"),
            ("engineer@garrisons.qa", "Civil Engineer"),
        ],
        "milestones": [
            ("Pre-start Survey", "Civil", 1, Decimal("25.00"), "in_progress"),
            ("Fit-Out Execution", "Fit-Out", 2, Decimal("0.00"), "not_started"),
        ],
        "boq": [
            (
                "FIT-001",
                "Demountable glass partitions",
                "Fit-Out",
                "Partitions",
                "m2",
                Decimal("180.000"),
                Decimal("310.00"),
            ),
            (
                "ELE-001",
                "Electrical containment",
                "MEP",
                "Electrical",
                "m",
                Decimal("320.000"),
                Decimal("35.00"),
            ),
        ],
    },
]


async def seed_launch_data() -> None:
    async with AsyncSessionLocal() as session:
        users = UserRepository(session)
        legacy_admin = await users.get_by_email("admin@garrisons.local")
        if legacy_admin:
            legacy_admin.employee_code = "LEGACY-ADMIN-001"
            legacy_admin.is_active = False
        created = 0
        updated = 0
        for seed_user in SEED_USERS:
            existing = await users.get_by_email(seed_user["email"])
            if existing:
                existing.full_name = seed_user["full_name"]
                existing.role = seed_user["role"]
                existing.employee_code = seed_user["employee_code"]
                existing.phone = seed_user["phone"]
                existing.designation = seed_user["designation"]
                updated += 1
                continue
            await users.add(
                User(
                    email=seed_user["email"],
                    full_name=seed_user["full_name"],
                    role=seed_user["role"],
                    employee_code=seed_user["employee_code"],
                    phone=seed_user["phone"],
                    designation=seed_user["designation"],
                    password_hash=hash_password(DEFAULT_PASSWORD),
                    must_change_password=True,
                )
            )
            created += 1
        await session.flush()

        user_by_email = {
            seed_user["email"]: await users.get_by_email(seed_user["email"])
            for seed_user in SEED_USERS
        }
        admin = user_by_email[DEFAULT_ADMIN_EMAIL]
        created_projects = 0
        updated_projects = 0
        for seed_project in SEED_PROJECTS:
            project = await session.scalar(
                select(Project).where(
                    Project.code == seed_project["code"],
                    Project.deleted_at.is_(None),
                )
            )
            if project:
                project.name = seed_project["name"]
                project.location = seed_project["location"]
                project.description = seed_project["description"]
                project.scope_of_work = seed_project["scope_of_work"]
                project.status = seed_project["status"]
                project.budget_amount = seed_project["budget_amount"]
                project.start_date = seed_project["start_date"]
                project.target_end_date = seed_project["target_end_date"]
                project.client_name = seed_project["client_name"]
                project.contract_number = seed_project["contract_number"]
                project.progress_percentage = seed_project["progress_percentage"]
                updated_projects += 1
            else:
                project = Project(
                    name=seed_project["name"],
                    code=seed_project["code"],
                    location=seed_project["location"],
                    description=seed_project["description"],
                    scope_of_work=seed_project["scope_of_work"],
                    status=seed_project["status"],
                    budget_amount=seed_project["budget_amount"],
                    start_date=seed_project["start_date"],
                    target_end_date=seed_project["target_end_date"],
                    client_name=seed_project["client_name"],
                    contract_number=seed_project["contract_number"],
                    progress_percentage=seed_project["progress_percentage"],
                    created_by=admin.id if admin else None,
                )
                session.add(project)
                await session.flush()
                created_projects += 1

            for member_email, role_in_project in seed_project["members"]:
                member_user = user_by_email[member_email]
                if not member_user:
                    continue
                existing_member = await session.scalar(
                    select(ProjectMember).where(
                        ProjectMember.project_id == project.id,
                        ProjectMember.user_id == member_user.id,
                        ProjectMember.deleted_at.is_(None),
                    )
                )
                if existing_member:
                    existing_member.role_in_project = role_in_project
                else:
                    session.add(
                        ProjectMember(
                            project_id=project.id,
                            user_id=member_user.id,
                            role_in_project=role_in_project,
                        )
                    )

            for milestone_name, discipline, sort_order, progress, status in seed_project[
                "milestones"
            ]:
                milestone = await session.scalar(
                    select(ProjectMilestone).where(
                        ProjectMilestone.project_id == project.id,
                        ProjectMilestone.name == milestone_name,
                        ProjectMilestone.deleted_at.is_(None),
                    )
                )
                if not milestone:
                    milestone = ProjectMilestone(
                        project_id=project.id,
                        name=milestone_name,
                        discipline=discipline,
                        planned_start_date=seed_project["start_date"],
                        planned_end_date=seed_project["target_end_date"],
                        sort_order=sort_order,
                    )
                    session.add(milestone)
                milestone.progress_percentage = progress
                milestone.status = status

            for item_code, description, discipline, phase, unit, quantity, rate in seed_project[
                "boq"
            ]:
                boq_item = await session.scalar(
                    select(BoqItem).where(
                        BoqItem.project_id == project.id,
                        BoqItem.item_code == item_code,
                        BoqItem.deleted_at.is_(None),
                    )
                )
                planned_amount = quantity * rate
                if not boq_item:
                    session.add(
                        BoqItem(
                            project_id=project.id,
                            item_code=item_code,
                            description=description,
                            discipline=discipline,
                            phase=phase,
                            unit=unit,
                            planned_quantity=quantity,
                            unit_rate=rate,
                            planned_amount=planned_amount,
                        )
                    )
                else:
                    boq_item.description = description
                    boq_item.discipline = discipline
                    boq_item.phase = phase
                    boq_item.unit = unit
                    boq_item.planned_quantity = quantity
                    boq_item.unit_rate = rate
                    boq_item.planned_amount = planned_amount

        await seed_daily_report(session, user_by_email)
        await session.commit()
        print(f"Seeded users: {created} created, {updated} updated")
        print(f"Seeded projects: {created_projects} created, {updated_projects} updated")
        print(f"Admin user: {DEFAULT_ADMIN_EMAIL}")
        print(f"Temporary password: {DEFAULT_ADMIN_PASSWORD}")


async def seed_daily_report(session, user_by_email: dict[str, User | None]) -> None:
    engineer = user_by_email["engineer@garrisons.qa"]
    project = await session.scalar(
        select(Project).where(Project.code == "GIP-001", Project.deleted_at.is_(None))
    )
    if not engineer or not project:
        return
    existing_report = await session.scalar(
        select(DailyReport).where(
            DailyReport.project_id == project.id,
            DailyReport.report_number == "DR-GIP-001-SEED",
            DailyReport.deleted_at.is_(None),
        )
    )
    if existing_report:
        return
    report = DailyReport(
        project_id=project.id,
        engineer_id=engineer.id,
        report_number="DR-GIP-001-SEED",
        report_date=date.today(),
        work_location="Villa A - Ground Floor",
        manpower_total=18,
        overtime_hours=Decimal("6.00"),
        work_completed="Completed blockwork alignment and started plaster preparation.",
        progress_percentage=Decimal("36.00"),
        safety_incidents=0,
        safety_notes="Toolbox talk completed before site start.",
        wir_status="pending",
        inspection_status="not_requested",
        delay_notes=None,
        next_day_plan="Continue internal plaster and coordinate material delivery.",
        supervisor_update_ids=[],
        photo_refs=[],
        attachment_refs=[],
        status="submitted",
        extra_fields={"seed_data": True, "uat_scenario": "approval"},
    )
    report.manpower_entries = [
        ReportManpower(trade="Mason", count=8, overtime_hours=Decimal("2.00")),
        ReportManpower(trade="Helper", count=10, overtime_hours=Decimal("4.00")),
    ]
    report.equipment_entries = [
        ReportEquipment(
            equipment_name="Concrete Mixer",
            quantity=1,
            hours_used=Decimal("5.00"),
            remarks="Shared with plaster team",
        )
    ]
    report.material_consumption = [
        ReportMaterialConsumption(
            material_name="Cement",
            unit="bag",
            quantity=Decimal("42.000"),
            remarks="Issued from site store",
        )
    ]
    session.add(report)


def main() -> None:
    asyncio.run(seed_launch_data())


if __name__ == "__main__":
    main()
