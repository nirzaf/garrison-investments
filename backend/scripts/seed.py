import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.database import AsyncSessionLocal
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.security import hash_password

DEFAULT_ADMIN_EMAIL = "admin@garrisons.qa"
DEFAULT_ADMIN_PASSWORD = "ChangeMe123!"
DEFAULT_PASSWORD = "ChangeMe123!"

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


async def seed_admin_user() -> None:
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
        await session.commit()
        print(f"Seeded users: {created} created, {updated} updated")
        print(f"Admin user: {DEFAULT_ADMIN_EMAIL}")
        print(f"Temporary password: {DEFAULT_ADMIN_PASSWORD}")


def main() -> None:
    asyncio.run(seed_admin_user())


if __name__ == "__main__":
    main()
