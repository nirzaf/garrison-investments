import asyncio
import base64
import os
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from minio.error import S3Error
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.approval import Approval
from app.models.boq_item import BoqItem
from app.models.daily_report import (
    DailyReport,
    ReportEquipment,
    ReportManpower,
    ReportMaterialConsumption,
)
from app.models.document import Document, DocumentVersion
from app.models.finance import Invoice, Payment
from app.models.import_batch import ImportBatch
from app.models.inventory import (
    InventoryAsset,
    InventoryItem,
    InventoryLocationStock,
    InventoryMovement,
    MaterialRequest,
    MaterialRequestLine,
    StorageLocation,
)
from app.models.notification import Notification
from app.models.photo import Photo
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_milestone import ProjectMilestone
from app.models.project_task import ProjectTask
from app.models.report_export import ReportExport
from app.models.supervisor_update import SupervisorUpdate
from app.models.supplier import Supplier
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.storage_service import minio_client
from app.utils.security import hash_password, validate_password_policy

DEFAULT_ADMIN_EMAIL = "admin.test@garrisons.lk"
LOCAL_DEMO_PASSWORD = "ChangeMe123!"
SEED_JPEG_BYTES = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////"
    "////////////////////////////////////////////2wBDAf//////////////////////////////"
    "////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB"
    "/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAA"
    "AAH/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAEFAqf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA"
    "/9oACAEDAQE/ASP/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/ASP/xAAUEAEAAAAAAAAA"
    "AAAAAAAAAAAA/9oACAEBAAY/Al//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/IV//2gA"
    "MAwEAAgADAAAAEP/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8QH//EABQRAQAAAAAAAA"
    "AAAAAAAAAAABD/2gAIAQIBAT8QH//EABQQAQAAAAAAAAAAAAAAAAAAABD/2gAIAQEAAT8QH//Z"
)
SEED_PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def get_asset_bytes(filename: str, default_bytes: bytes) -> bytes:
    filepath = ASSETS_DIR / filename
    if filepath.exists():
        try:
            return filepath.read_bytes()
        except Exception:
            pass
    return default_bytes


SEED_PHOTO_OBJECTS = {
    "seed-photos/site_overview.jpg": (
        "image/jpeg",
        get_asset_bytes("site_overview.jpg", SEED_JPEG_BYTES),
    ),
    "seed-photos/site_overview_compressed.jpg": (
        "image/jpeg",
        get_asset_bytes("site_overview_compressed.jpg", SEED_JPEG_BYTES),
    ),
    "seed-photos/site_overview_thumb.jpg": (
        "image/jpeg",
        get_asset_bytes("site_overview_thumb.jpg", SEED_JPEG_BYTES),
    ),
    "seed-photos/blockwork_day5.jpg": (
        "image/jpeg",
        get_asset_bytes("blockwork_day5.jpg", SEED_JPEG_BYTES),
    ),
    "seed-photos/blockwork_day5_compressed.jpg": (
        "image/jpeg",
        get_asset_bytes("blockwork_day5_compressed.jpg", SEED_JPEG_BYTES),
    ),
    "seed-photos/blockwork_day5_thumb.jpg": (
        "image/jpeg",
        get_asset_bytes("blockwork_day5_thumb.jpg", SEED_JPEG_BYTES),
    ),
    "seed-attachments/plaster_check.pdf": ("application/pdf", SEED_PDF_BYTES),
}
SEED_DOCUMENT_OBJECTS = {
    "seed-docs/pep_v1.pdf": ("application/pdf", SEED_PDF_BYTES),
    "seed-docs/pep_v2.pdf": ("application/pdf", SEED_PDF_BYTES),
    "seed-docs/mar_cement_mix_design.pdf": ("application/pdf", SEED_PDF_BYTES),
    "seed-docs/mir_steel_rebar_delivery.pdf": ("application/pdf", SEED_PDF_BYTES),
    "seed-docs/wir_plaster_zone_a.pdf": ("application/pdf", SEED_PDF_BYTES),
    "seed-docs/delivery_note_cement_batch001.pdf": ("application/pdf", SEED_PDF_BYTES),
}


def ensure_seed_storage_objects(objects: dict[str, tuple[str, bytes]]) -> None:
    settings = get_settings()
    client = minio_client(settings)
    force = (os.getenv("SEED_FORCE_STORAGE") == "true") or ("--force-storage" in sys.argv)
    try:
        if not client.bucket_exists(settings.minio_bucket):
            client.make_bucket(settings.minio_bucket)
        uploaded = 0
        for object_key, (content_type, data) in objects.items():
            try:
                stat = client.stat_object(settings.minio_bucket, object_key)
                is_placeholder = stat.size <= 2000
                has_real_data = len(data) > 2000
                if not force and not (is_placeholder and has_real_data):
                    continue
            except S3Error as exc:
                if exc.code not in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                    raise
            client.put_object(
                settings.minio_bucket,
                object_key,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            uploaded += 1
        print(f"Seeded storage objects: {uploaded} uploaded, {len(objects) - uploaded} existing")
    except Exception as exc:
        print(f"Skipped seed storage objects: {exc}")

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
        "email": "gm.test@garrisons.lk",
        "full_name": "General Manager",
        "role": "general_manager",
        "employee_code": "GM-001",
        "phone": "+97450000002",
        "designation": "General Manager",
    },
    {
        "email": "operations.test@garrisons.lk",
        "full_name": "Operation Manager",
        "role": "operation_manager",
        "employee_code": "OPS-001",
        "phone": "+97450000003",
        "designation": "Operation Manager",
    },
    {
        "email": "pm.test@garrisons.lk",
        "full_name": "Project Manager",
        "role": "project_manager",
        "employee_code": "PM-001",
        "phone": "+97450000004",
        "designation": "Project Manager",
    },
    {
        "email": "engineer.test@garrisons.lk",
        "full_name": "Civil Engineer",
        "role": "civil_engineer",
        "employee_code": "ENG-001",
        "phone": "+97450000005",
        "designation": "Civil Engineer",
    },
    {
        "email": "supervisor.test@garrisons.lk",
        "full_name": "Civil Supervisor",
        "role": "civil_supervisor",
        "employee_code": "SUP-001",
        "phone": "+97450000006",
        "designation": "Civil Supervisor",
    },
    {
        "email": "storekeeper.test@garrisons.lk",
        "full_name": "Store Keeper",
        "role": "store_keeper",
        "employee_code": "STORE-001",
        "phone": "+97450000007",
        "designation": "Store Keeper",
    },
    {
        "email": "accounts.test@garrisons.lk",
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
        "scope_of_work": (
            "Civil finishing, gypsum, paint, MEP coordination, and handover works."
        ),
        "status": "active",
        "budget_amount": Decimal("950000.00"),
        "start_date": date.today() - timedelta(days=30),
        "target_end_date": date.today() + timedelta(days=90),
        "client_name": "Garrisons Demo Client",
        "contract_number": "CNT-LUSAIL-001",
        "progress_percentage": Decimal("35.00"),
        "members": [
            ("pm.test@garrisons.lk", "Project Manager"),
            ("engineer.test@garrisons.lk", "Civil Engineer"),
            ("supervisor.test@garrisons.lk", "Civil Supervisor"),
            ("storekeeper.test@garrisons.lk", "Store Keeper"),
            ("accounts.test@garrisons.lk", "Accounts"),
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
        "description": (
            "Commercial renovation project used for approval and dashboard checks."
        ),
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
            ("operations.test@garrisons.lk", "Operation Manager"),
            ("pm.test@garrisons.lk", "Project Manager"),
            ("engineer.test@garrisons.lk", "Civil Engineer"),
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

SEED_SUPPLIERS = [
    {
        "name": "Qatar Building Materials Co.",
        "category": "Construction Materials",
        "rating": "approved",
        "payment_terms": "Net 30 Days",
        "contact_person": "Ahmed Al-Thani",
        "phone": "+97444123456",
        "email": "sales@qbmco.qa",
        "address": "Street 24, Industrial Area, Doha, Qatar",
        "tax_registration_number": "QAT-123456789",
        "tds_certificate_number": "TDS-QBM-2026-001",
        "tds_expiry_date": date.today() + timedelta(days=180),
        "compliance_status": "compliant",
    },
    {
        "name": "Doha Steel & Hardware WLL",
        "category": "Steel & Hardware",
        "rating": "approved",
        "payment_terms": "Net 45 Days",
        "contact_person": "Mohammed Al-Sulaiti",
        "phone": "+97444234567",
        "email": "orders@dohasteel.qa",
        "address": "Zone 56, Street 12, New Industrial Area, Doha, Qatar",
        "tax_registration_number": "QAT-987654321",
        "tds_certificate_number": "TDS-DSH-2026-002",
        "tds_expiry_date": date.today() + timedelta(days=90),
        "compliance_status": "compliant",
    },
    {
        "name": "Gulf Electrical Supplies LLC",
        "category": "Electrical & MEP",
        "rating": "conditional",
        "payment_terms": "Net 30 Days",
        "contact_person": "Fatima Al-Mansoori",
        "phone": "+97444345678",
        "email": "info@gulfelectrical.qa",
        "address": "Building 14, Salwa Road, Doha, Qatar",
        "tax_registration_number": "QAT-456789123",
        "tds_certificate_number": None,
        "tds_expiry_date": None,
        "compliance_status": "pending_documents",
    },
]

SEED_INVENTORY_ITEMS = [
    {
        "name": "Portland Cement (50kg)",
        "item_code": "MAT-CEM-001",
        "category": "Bulk Materials",
        "item_type": "consumable",
        "unit": "bag",
        "minimum_stock": Decimal("100.000"),
        "reorder_level": Decimal("200.000"),
        "unit_cost": Decimal("22.50"),
        "supplier_email": "sales@qbmco.qa",
    },
    {
        "name": "Steel Rebar 12mm",
        "item_code": "MAT-STL-001",
        "category": "Steel",
        "item_type": "consumable",
        "unit": "ton",
        "minimum_stock": Decimal("1.000"),
        "reorder_level": Decimal("2.500"),
        "unit_cost": Decimal("2850.00"),
        "supplier_email": "orders@dohasteel.qa",
    },
    {
        "name": "Emulsion Paint (White, 20L)",
        "item_code": "MAT-PNT-001",
        "category": "Finishes",
        "item_type": "consumable",
        "unit": "pail",
        "minimum_stock": Decimal("10.000"),
        "reorder_level": Decimal("25.000"),
        "unit_cost": Decimal("165.00"),
        "supplier_email": None,
    },
    {
        "name": "PVC Conduit 25mm",
        "item_code": "MAT-ELE-001",
        "category": "Electrical",
        "item_type": "consumable",
        "unit": "m",
        "minimum_stock": Decimal("200.000"),
        "reorder_level": Decimal("500.000"),
        "unit_cost": Decimal("4.50"),
        "supplier_email": "info@gulfelectrical.qa",
    },
    {
        "name": "Concrete Mixer (Electric)",
        "item_code": "EQU-MIX-001",
        "category": "Equipment",
        "item_type": "asset",
        "unit": "unit",
        "minimum_stock": Decimal("0"),
        "reorder_level": Decimal("0"),
        "unit_cost": Decimal("12500.00"),
        "supplier_email": None,
    },
    {
        "name": "Safety Helmet",
        "item_code": "PPE-HEL-001",
        "category": "PPE",
        "item_type": "consumable",
        "unit": "Nos",
        "minimum_stock": Decimal("20.000"),
        "reorder_level": Decimal("50.000"),
        "unit_cost": Decimal("35.00"),
        "supplier_email": None,
    },
    {
        "name": "Tile Adhesive",
        "item_code": "MAT-ADH-001",
        "category": "Finishes",
        "item_type": "consumable",
        "unit": "KG",
        "minimum_stock": Decimal("250.000"),
        "reorder_level": Decimal("500.000"),
        "unit_cost": Decimal("2.40"),
        "supplier_email": "sales@qbmco.qa",
    },
    {
        "name": "Gypsum Board 12mm",
        "item_code": "MAT-GYP-001",
        "category": "Finishes",
        "item_type": "consumable",
        "unit": "SQM",
        "minimum_stock": Decimal("100.000"),
        "reorder_level": Decimal("180.000"),
        "unit_cost": Decimal("18.00"),
        "supplier_email": None,
    },
]

SEED_LOCATIONS = [
    {
        "name": "GIP-001 Site Store",
        "code": "LOC-GIP001-STORE",
        "location_type": "site_store",
        "address": "Lusail Villa A, Ground Floor Storage Room",
    },
    {
        "name": "Central Warehouse",
        "code": "LOC-CENTRAL-WH",
        "location_type": "warehouse",
        "address": "Industrial Area, Street 24, Doha",
    },
    {
        "name": "GIP-002 Site Store",
        "code": "LOC-GIP002-STORE",
        "location_type": "site_store",
        "address": "West Bay Tower, Basement Level 1",
    },
]


async def seed_launch_data() -> None:
    environment = get_settings().app_env.strip().lower()
    if environment not in {"development", "local", "test", "staging"}:
        raise SystemExit("Demo data can only be seeded in development, test, or staging.")

    password = os.getenv("SEED_DEFAULT_PASSWORD")
    if environment == "staging" and (not password or password == LOCAL_DEMO_PASSWORD):
        raise SystemExit("Set a unique SEED_DEFAULT_PASSWORD before seeding staging.")
    password = password or LOCAL_DEMO_PASSWORD
    validate_password_policy(password)

    async with AsyncSessionLocal() as session:
        users = UserRepository(session)
        legacy_admin = await users.get_by_email("admin@garrisons.local")
        if legacy_admin:
            legacy_admin.employee_code = "LEGACY-ADMIN-001"
            legacy_admin.is_active = False

        seed_password_hash = hash_password(password)
        created_users = 0
        updated_users = 0
        for seed_user in SEED_USERS:
            email = seed_user["email"].lower()
            employee_code = seed_user["employee_code"]

            existing_by_email = await users.get_by_email(email)
            existing_by_employee_code = None
            if employee_code:
                existing_by_employee_code = await session.scalar(
                    select(User).where(
                        User.employee_code == employee_code,
                        User.deleted_at.is_(None),
                    )
                )

            existing = existing_by_email or existing_by_employee_code
            if existing:
                if (
                    existing_by_email
                    and existing_by_employee_code
                    and existing_by_email.id != existing_by_employee_code.id
                ):
                    existing_by_employee_code.employee_code = None

                existing.email = email
                existing.full_name = seed_user["full_name"]
                existing.role = seed_user["role"]
                existing.employee_code = employee_code
                existing.phone = seed_user["phone"]
                existing.designation = seed_user["designation"]
                existing.password_hash = seed_password_hash
                existing.must_change_password = True
                existing.is_active = True
                existing.failed_login_attempts = 0
                existing.locked_until = None
                updated_users += 1
                continue
            await users.add(
                User(
                    email=email,
                    full_name=seed_user["full_name"],
                    role=seed_user["role"],
                    employee_code=employee_code,
                    phone=seed_user["phone"],
                    designation=seed_user["designation"],
                    password_hash=seed_password_hash,
                    must_change_password=True,
                )
            )
            created_users += 1
        await session.flush()

        user_by_email = {
            seed_user["email"]: await users.get_by_email(seed_user["email"])
            for seed_user in SEED_USERS
        }
        admin = user_by_email[DEFAULT_ADMIN_EMAIL]

        created_projects = 0
        updated_projects = 0
        project_objects: dict[str, Project] = {}
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
            project_objects[seed_project["code"]] = project

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

            for milestone_name, discipline, sort_order, progress, status in (
                seed_project["milestones"]
            ):
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

            for item_code, description, discipline, phase, unit, quantity, rate in (
                seed_project["boq"]
            ):
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

        await seed_daily_reports(session, user_by_email, project_objects)
        await seed_project_tasks(session, user_by_email, project_objects)
        suppliers = await seed_suppliers(session, user_by_email)
        inventory_items, locations = await seed_inventory(
            session, user_by_email, project_objects, suppliers
        )
        await seed_inventory_movements(
            session, user_by_email, project_objects, inventory_items, locations
        )
        await seed_material_requests(
            session, user_by_email, project_objects, inventory_items, locations
        )
        await seed_finance(
            session, user_by_email, project_objects, suppliers
        )
        await seed_supervisor_updates(session, user_by_email, project_objects)
        await seed_photos(session, user_by_email, project_objects)
        await seed_documents(session, user_by_email, project_objects)
        await seed_approvals(session, user_by_email, project_objects)
        await seed_notifications(session, user_by_email, project_objects)
        await seed_activity_logs(session, user_by_email, project_objects)
        await seed_report_exports(session, user_by_email, project_objects)
        await seed_import_batches(session, user_by_email)

        await session.commit()
        print(f"Seeded users: {created_users} created, {updated_users} updated")
        print(f"Seeded projects: {created_projects} created, {updated_projects} updated")
        print(f"Admin user: {DEFAULT_ADMIN_EMAIL}")


async def seed_suppliers(session, user_by_email: dict) -> dict[str, Supplier]:
    supplier_map: dict[str, Supplier] = {}
    created = 0
    for s in SEED_SUPPLIERS:
        existing = await session.scalar(
            select(Supplier).where(
                Supplier.name == s["name"],
                Supplier.deleted_at.is_(None),
            )
        )
        if existing:
            existing.category = s["category"]
            existing.rating = s["rating"]
            existing.payment_terms = s["payment_terms"]
            existing.contact_person = s["contact_person"]
            existing.phone = s["phone"]
            existing.email = s["email"]
            existing.address = s["address"]
            existing.tax_registration_number = s["tax_registration_number"]
            existing.tds_certificate_number = s["tds_certificate_number"]
            existing.tds_expiry_date = s["tds_expiry_date"]
            existing.compliance_status = s["compliance_status"]
            supplier_map[s["email"]] = existing
            continue
        supplier = Supplier(
            name=s["name"],
            category=s["category"],
            rating=s["rating"],
            payment_terms=s["payment_terms"],
            contact_person=s["contact_person"],
            phone=s["phone"],
            email=s["email"],
            address=s["address"],
            tax_registration_number=s["tax_registration_number"],
            tds_certificate_number=s["tds_certificate_number"],
            tds_expiry_date=s["tds_expiry_date"],
            compliance_status=s["compliance_status"],
        )
        session.add(supplier)
        await session.flush()
        supplier_map[s["email"]] = supplier
        created += 1
    print(f"Seeded suppliers: {created} created, {len(SEED_SUPPLIERS) - created} updated")
    return supplier_map


async def seed_project_tasks(
    session,
    user_by_email: dict,
    project_objects: dict[str, Project],
) -> None:
    project = project_objects.get("GIP-001")
    if not project:
        return
    engineer = user_by_email.get("engineer.test@garrisons.lk")
    supervisor = user_by_email.get("supervisor.test@garrisons.lk")
    milestone = await session.scalar(
        select(ProjectMilestone).where(
            ProjectMilestone.project_id == project.id,
            ProjectMilestone.name == "Blockwork And Plaster",
            ProjectMilestone.deleted_at.is_(None),
        )
    )
    first_task = await upsert_project_task(
        session,
        project_id=project.id,
        name="Complete level 1 blockwork",
        milestone_id=milestone.id if milestone else None,
        owner_id=supervisor.id if supervisor else None,
        dependency_task_id=None,
        baseline_start_date=date.today() - timedelta(days=10),
        baseline_end_date=date.today() + timedelta(days=5),
        actual_start_date=date.today() - timedelta(days=9),
        actual_end_date=None,
        progress_percentage=Decimal("65.00"),
        status="in_progress",
        delay_reason="Awaiting final MEP sleeve clearance in corridor B.",
        sort_order=1,
    )
    await upsert_project_task(
        session,
        project_id=project.id,
        name="Engineer plaster inspection sign-off",
        milestone_id=milestone.id if milestone else None,
        owner_id=engineer.id if engineer else None,
        dependency_task_id=first_task.id,
        baseline_start_date=date.today() + timedelta(days=6),
        baseline_end_date=date.today() + timedelta(days=10),
        actual_start_date=None,
        actual_end_date=None,
        progress_percentage=Decimal("0.00"),
        status="not_started",
        delay_reason=None,
        sort_order=2,
    )


async def upsert_project_task(
    session,
    *,
    project_id,
    name: str,
    milestone_id,
    owner_id,
    dependency_task_id,
    baseline_start_date,
    baseline_end_date,
    actual_start_date,
    actual_end_date,
    progress_percentage: Decimal,
    status: str,
    delay_reason: str | None,
    sort_order: int,
) -> ProjectTask:
    task = await session.scalar(
        select(ProjectTask).where(
            ProjectTask.project_id == project_id,
            ProjectTask.name == name,
            ProjectTask.deleted_at.is_(None),
        )
    )
    if not task:
        task = ProjectTask(project_id=project_id, name=name)
        session.add(task)
        await session.flush()
    task.milestone_id = milestone_id
    task.owner_id = owner_id
    task.dependency_task_id = dependency_task_id
    task.baseline_start_date = baseline_start_date
    task.baseline_end_date = baseline_end_date
    task.actual_start_date = actual_start_date
    task.actual_end_date = actual_end_date
    task.progress_percentage = progress_percentage
    task.status = status
    task.delay_reason = delay_reason
    task.sort_order = sort_order
    return task


async def seed_inventory(
    session, user_by_email: dict, project_objects: dict, suppliers: dict
) -> tuple[dict[str, InventoryItem], dict[str, StorageLocation]]:
    gip001 = project_objects.get("GIP-001")
    gip002 = project_objects.get("GIP-002")

    location_map: dict[str, StorageLocation] = {}
    for loc in SEED_LOCATIONS:
        existing = await session.scalar(
            select(StorageLocation).where(
                StorageLocation.code == loc["code"],
                StorageLocation.deleted_at.is_(None),
            )
        )
        if existing:
            existing.name = loc["name"]
            existing.location_type = loc["location_type"]
            existing.address = loc["address"]
            existing.project_id = (
                gip001.id
                if gip001 and "GIP001" in loc["code"]
                else (gip002.id if gip002 and "GIP002" in loc["code"] else None)
            )
            location_map[loc["code"]] = existing
            continue
        sl = StorageLocation(
            name=loc["name"],
            code=loc["code"],
            location_type=loc["location_type"],
            address=loc["address"],
            project_id=gip001.id
            if "GIP001" in loc["code"]
            else (gip002.id if gip002 and "GIP002" in loc["code"] else None),
        )
        session.add(sl)
        await session.flush()
        location_map[loc["code"]] = sl

    supplier_by_email = {s.email: s for s in suppliers.values()} if suppliers else {}

    item_map: dict[str, InventoryItem] = {}
    for it in SEED_INVENTORY_ITEMS:
        existing = await session.scalar(
            select(InventoryItem).where(
                InventoryItem.item_code == it["item_code"],
                InventoryItem.deleted_at.is_(None),
            )
        )
        if existing:
            existing.name = it["name"]
            existing.category = it["category"]
            existing.item_type = it["item_type"]
            existing.unit = it["unit"]
            existing.minimum_stock = it["minimum_stock"]
            existing.reorder_level = it["reorder_level"]
            existing.unit_cost = it["unit_cost"]
            item_map[it["item_code"]] = existing
            continue
        sup = supplier_by_email.get(it["supplier_email"]) if it["supplier_email"] else None
        item = InventoryItem(
            name=it["name"],
            item_code=it["item_code"],
            category=it["category"],
            item_type=it["item_type"],
            unit=it["unit"],
            minimum_stock=it["minimum_stock"],
            reorder_level=it["reorder_level"],
            unit_cost=it["unit_cost"],
            supplier_id=sup.id if sup else None,
        )
        session.add(item)
        await session.flush()
        item_map[it["item_code"]] = item

    stock_data = [
        ("MAT-CEM-001", "LOC-GIP001-STORE", Decimal("350.000"), Decimal("50.000")),
        ("MAT-CEM-001", "LOC-CENTRAL-WH", Decimal("500.000"), Decimal("0")),
        ("MAT-STL-001", "LOC-GIP001-STORE", Decimal("3.500"), Decimal("0.500")),
        ("MAT-STL-001", "LOC-CENTRAL-WH", Decimal("8.000"), Decimal("0")),
        ("MAT-PNT-001", "LOC-GIP001-STORE", Decimal("30.000"), Decimal("5.000")),
        ("MAT-PNT-001", "LOC-CENTRAL-WH", Decimal("45.000"), Decimal("0")),
        ("MAT-ELE-001", "LOC-GIP001-STORE", Decimal("600.000"), Decimal("100.000")),
        ("MAT-ELE-001", "LOC-GIP002-STORE", Decimal("200.000"), Decimal("0")),
        ("EQU-MIX-001", "LOC-GIP001-STORE", Decimal("2.000"), Decimal("0")),
        ("PPE-HEL-001", "LOC-GIP001-STORE", Decimal("40.000"), Decimal("10.000")),
        ("PPE-HEL-001", "LOC-CENTRAL-WH", Decimal("80.000"), Decimal("0")),
        ("MAT-ADH-001", "LOC-GIP001-STORE", Decimal("620.000"), Decimal("120.000")),
        ("MAT-GYP-001", "LOC-GIP001-STORE", Decimal("240.000"), Decimal("35.000")),
    ]
    for item_code, loc_code, on_hand, reserved in stock_data:
        item = item_map[item_code]
        loc = location_map[loc_code]
        existing = await session.scalar(
            select(InventoryLocationStock).where(
                InventoryLocationStock.item_id == item.id,
                InventoryLocationStock.location_id == loc.id,
                InventoryLocationStock.deleted_at.is_(None),
            )
        )
        if existing:
            existing.on_hand_qty = on_hand
            existing.reserved_qty = reserved
        else:
            session.add(
                InventoryLocationStock(
                    item_id=item.id,
                    location_id=loc.id,
                    on_hand_qty=on_hand,
                    reserved_qty=reserved,
                )
            )

    mixer_item = item_map["EQU-MIX-001"]
    mixer_loc = location_map["LOC-GIP001-STORE"]
    existing_asset = await session.scalar(
        select(InventoryAsset).where(
            InventoryAsset.item_id == mixer_item.id,
            InventoryAsset.asset_tag == "EQ-MIX-001-A",
            InventoryAsset.deleted_at.is_(None),
        )
    )
    if not existing_asset:
        session.add(
            InventoryAsset(
                item_id=mixer_item.id,
                asset_tag="EQ-MIX-001-A",
                current_location_id=mixer_loc.id,
                condition="good",
                status="active",
            )
        )
        session.add(
            InventoryAsset(
                item_id=mixer_item.id,
                asset_tag="EQ-MIX-001-B",
                current_location_id=mixer_loc.id,
                condition="needs_maintenance",
                status="active",
            )
        )

    print("Seeded inventory: items, locations, stock, assets")
    return item_map, location_map


async def seed_inventory_movements(
    session, user_by_email: dict, project_objects: dict,
    item_map: dict, location_map: dict
) -> None:
    store = user_by_email.get("storekeeper.test@garrisons.lk")
    if not store:
        return
    gip001 = project_objects.get("GIP-001")
    site_store = location_map.get("LOC-GIP001-STORE")
    central_wh = location_map.get("LOC-CENTRAL-WH")
    cement = item_map.get("MAT-CEM-001")
    paint = item_map.get("MAT-PNT-001")
    rebar = item_map.get("MAT-STL-001")
    now = datetime.now(UTC)

    movements = [
        InventoryMovement(
            item_id=cement.id,
            movement_type="transfer",
            quantity=Decimal("200.000"),
            from_location_id=central_wh.id,
            to_location_id=site_store.id,
            project_id=gip001.id if gip001 else None,
            reference_type="stock_replenish",
            handled_by=store.id,
            notes="Weekly replenishment to site store",
            created_at=now - timedelta(days=7),
        ),
        InventoryMovement(
            item_id=cement.id,
            movement_type="consumption",
            quantity=Decimal("42.000"),
            from_location_id=site_store.id,
            to_location_id=None,
            project_id=gip001.id if gip001 else None,
            reference_type="daily_report",
            handled_by=store.id,
            notes="Issued for daily plaster work",
            created_at=now - timedelta(days=2),
        ),
        InventoryMovement(
            item_id=rebar.id,
            movement_type="transfer",
            quantity=Decimal("1.500"),
            from_location_id=central_wh.id,
            to_location_id=site_store.id,
            project_id=gip001.id if gip001 else None,
            reference_type="stock_replenish",
            handled_by=store.id,
            notes="Rebar delivery to site",
            created_at=now - timedelta(days=5),
        ),
        InventoryMovement(
            item_id=paint.id,
            movement_type="transfer",
            quantity=Decimal("10.000"),
            from_location_id=central_wh.id,
            to_location_id=site_store.id,
            project_id=gip001.id if gip001 else None,
            reference_type="stock_replenish",
            handled_by=store.id,
            notes="Paint stock transfer for upcoming finishing work",
            created_at=now - timedelta(days=3),
        ),
        InventoryMovement(
            item_id=cement.id,
            movement_type="adjustment",
            quantity=Decimal("5.000"),
            from_location_id=site_store.id,
            to_location_id=None,
            project_id=gip001.id if gip001 else None,
            reference_type="stock_count",
            handled_by=store.id,
            notes="Stock adjustment after physical count — 5 bags damaged",
            created_at=now - timedelta(days=1),
        ),
        InventoryMovement(
            item_id=cement.id,
            movement_type="return",
            quantity=Decimal("3.000"),
            from_location_id=None,
            to_location_id=site_store.id,
            project_id=gip001.id if gip001 else None,
            reference_type="return",
            handled_by=store.id,
            notes="Unused bags returned from site",
            created_at=now - timedelta(hours=12),
        ),
    ]
    created = 0
    for m in movements:
        existing = await session.scalar(
            select(InventoryMovement).where(
                InventoryMovement.item_id == m.item_id,
                InventoryMovement.movement_type == m.movement_type,
                InventoryMovement.quantity == m.quantity,
                InventoryMovement.reference_type == m.reference_type,
                InventoryMovement.notes == m.notes,
                InventoryMovement.deleted_at.is_(None),
            )
        )
        if existing:
            continue
        session.add(m)
        created += 1
    print(f"Seeded inventory movements: {created} created, {len(movements) - created} existing")


async def seed_material_requests(
    session, user_by_email: dict, project_objects: dict,
    item_map: dict, location_map: dict
) -> None:
    engineer = user_by_email.get("engineer.test@garrisons.lk")
    gip001 = project_objects.get("GIP-001")
    site_store = location_map.get("LOC-GIP001-STORE")
    if not engineer or not gip001 or not site_store:
        return
    cement = item_map.get("MAT-CEM-001")
    paint = item_map.get("MAT-PNT-001")
    helmet = item_map.get("PPE-HEL-001")

    req_num = "MR-GIP001-SEED-001"
    existing = await session.scalar(
        select(MaterialRequest).where(
            MaterialRequest.request_number == req_num,
            MaterialRequest.deleted_at.is_(None),
        )
    )
    if existing:
        return
    request = MaterialRequest(
        request_number=req_num,
        project_id=gip001.id,
        requester_id=engineer.id,
        from_location_id=site_store.id,
        status="approved",
        total_estimated_cost=Decimal("2165.00"),
        notes="Materials needed for plaster preparation work",
    )
    session.add(request)
    await session.flush()

    session.add(
        MaterialRequestLine(
            request_id=request.id,
            item_id=cement.id,
            quantity=Decimal("50.000"),
            reserved_quantity=Decimal("50.000"),
            issued_quantity=Decimal("42.000"),
            unit_cost=cement.unit_cost,
        )
    )
    session.add(
        MaterialRequestLine(
            request_id=request.id,
            item_id=paint.id,
            quantity=Decimal("5.000"),
            reserved_quantity=Decimal("5.000"),
            issued_quantity=Decimal("0"),
            unit_cost=paint.unit_cost,
        )
    )
    session.add(
        MaterialRequestLine(
            request_id=request.id,
            item_id=helmet.id,
            quantity=Decimal("10.000"),
            reserved_quantity=Decimal("10.000"),
            issued_quantity=Decimal("10.000"),
            unit_cost=helmet.unit_cost,
        )
    )

    req_num2 = "MR-GIP001-SEED-002"
    if not await session.scalar(
        select(MaterialRequest).where(
            MaterialRequest.request_number == req_num2,
            MaterialRequest.deleted_at.is_(None),
        )
    ):
        request2 = MaterialRequest(
            request_number=req_num2,
            project_id=gip001.id,
            requester_id=engineer.id,
            from_location_id=site_store.id,
            status="requested",
            total_estimated_cost=Decimal("8550.00"),
            notes="Rebar for upcoming structural work",
        )
        session.add(request2)
        await session.flush()
        rebar = item_map.get("MAT-STL-001")
        session.add(
            MaterialRequestLine(
                request_id=request2.id,
                item_id=rebar.id,
                quantity=Decimal("3.000"),
                reserved_quantity=Decimal("0"),
                issued_quantity=Decimal("0"),
                unit_cost=rebar.unit_cost,
            )
        )
    print("Seeded material requests: 2 records with lines")


async def seed_finance(
    session, user_by_email: dict, project_objects: dict, suppliers: dict
) -> None:
    accounts = user_by_email.get("accounts.test@garrisons.lk")
    gip001 = project_objects.get("GIP-001")
    if not accounts or not gip001:
        return

    supplier_list = list(suppliers.values())
    sup_qbm = supplier_list[0] if len(supplier_list) > 0 else None
    sup_steel = supplier_list[1] if len(supplier_list) > 1 else None
    now = datetime.now(UTC)

    inv_num = "INV-GIP001-SEED-001"
    existing_inv = await session.scalar(
        select(Invoice).where(
            Invoice.invoice_number == inv_num,
            Invoice.deleted_at.is_(None),
        )
    )
    if not existing_inv and sup_qbm:
        invoice1 = Invoice(
            invoice_number=inv_num,
            project_id=gip001.id,
            supplier_id=sup_qbm.id,
            invoice_date=date.today() - timedelta(days=15),
            due_date=date.today() + timedelta(days=15),
            amount=Decimal("22500.00"),
            tax_amount=Decimal("1125.00"),
            total_amount=Decimal("23625.00"),
            status="approved",
            payment_status="partial",
            created_by=accounts.id,
            approved_by=user_by_email.get("pm.test@garrisons.lk").id
            if user_by_email.get("pm.test@garrisons.lk")
            else None,
            approved_at=now - timedelta(days=13),
            notes="Cement and plaster materials for Blockwork phase",
        )
        session.add(invoice1)
        await session.flush()

        session.add(
            Payment(
                invoice_id=invoice1.id,
                payment_date=date.today() - timedelta(days=10),
                amount=Decimal("12000.00"),
                method="bank_transfer",
                reference_number="TXN-QNB-2026-001",
                recorded_by=accounts.id,
                notes="Partial payment — 50% advance",
            )
        )

    inv_num2 = "INV-GIP001-SEED-002"
    existing_inv2 = await session.scalar(
        select(Invoice).where(
            Invoice.invoice_number == inv_num2,
            Invoice.deleted_at.is_(None),
        )
    )
    if not existing_inv2 and sup_steel:
        invoice2 = Invoice(
            invoice_number=inv_num2,
            project_id=gip001.id,
            supplier_id=sup_steel.id,
            invoice_date=date.today() - timedelta(days=5),
            due_date=date.today() + timedelta(days=40),
            amount=Decimal("9975.00"),
            tax_amount=Decimal("498.75"),
            total_amount=Decimal("10473.75"),
            status="submitted",
            payment_status="unpaid",
            created_by=accounts.id,
            notes="Steel rebar delivery — 3.5 tons",
        )
        session.add(invoice2)
        await session.flush()

        session.add(
            Payment(
                invoice_id=invoice2.id,
                payment_date=date.today() - timedelta(days=1),
                amount=Decimal("5000.00"),
                method="cheque",
                reference_number="CHQ-001234",
                recorded_by=accounts.id,
                notes="Partial advance payment",
            )
        )
    print("Seeded finance: invoices and payments")


async def seed_supervisor_updates(
    session, user_by_email: dict, project_objects: dict
) -> None:
    supervisor = user_by_email.get("supervisor.test@garrisons.lk")
    gip001 = project_objects.get("GIP-001")
    if not supervisor or not gip001:
        return

    update_data = [
        {
            "update_date": date.today() - timedelta(days=3),
            "day_type": "weekday",
            "work_location": "Villa A - Ground Floor",
            "attendance_count": 18,
            "overtime_hours": Decimal("4.00"),
            "progress_notes": (
                "Blockwork for internal walls completed. Plaster scratch coat applied in "
                "3 rooms."
            ),
            "delay_notes": None,
            "required_notes": (
                "Need additional cement bags by tomorrow AM. Mixer B needs servicing."
            ),
            "status": "verified",
        },
        {
            "update_date": date.today() - timedelta(days=1),
            "day_type": "weekday",
            "work_location": "Villa A - Ground Floor & First Floor",
            "attendance_count": 22,
            "overtime_hours": Decimal("6.00"),
            "progress_notes": (
                "Plaster work continued. First floor blockwork alignment started. "
                "MEP rough-in coordination completed."
            ),
            "delay_notes": "Minor delay due to rain — 2 hours lost in outdoor work",
            "required_notes": "Coordinate with MEP team for ceiling conduit routing.",
            "status": "submitted",
        },
        {
            "update_date": date.today(),
            "day_type": "weekday",
            "work_location": "Villa A - First Floor",
            "attendance_count": 20,
            "overtime_hours": Decimal("3.00"),
            "progress_notes": (
                "First floor plaster scratch coat applied in 5 rooms. "
                "Started ceiling grid layout."
            ),
            "delay_notes": None,
            "required_notes": "Request paint samples for client approval next week.",
            "status": "draft",
        },
    ]
    created = 0
    engineer = user_by_email.get("engineer.test@garrisons.lk")
    for u in update_data:
        existing = await session.scalar(
            select(SupervisorUpdate).where(
                SupervisorUpdate.project_id == gip001.id,
                SupervisorUpdate.supervisor_id == supervisor.id,
                SupervisorUpdate.update_date == u["update_date"],
                SupervisorUpdate.deleted_at.is_(None),
            )
        )
        if existing:
            continue
        update = SupervisorUpdate(
            project_id=gip001.id,
            supervisor_id=supervisor.id,
            update_date=u["update_date"],
            day_type=u["day_type"],
            work_location=u["work_location"],
            attendance_count=u["attendance_count"],
            overtime_hours=u["overtime_hours"],
            progress_notes=u["progress_notes"],
            delay_notes=u["delay_notes"],
            required_notes=u["required_notes"],
            attachment_refs=[
                {"name": "site_photo_1.jpg", "type": "image/jpeg", "kind": "photo"},
            ],
            status=u["status"],
            submitted_at=datetime.now(UTC) - timedelta(days=1)
            if u["status"] != "draft"
            else None,
            verified_by=engineer.id if u["status"] == "verified" else None,
            verified_at=datetime.now(UTC) - timedelta(days=2)
            if u["status"] == "verified"
            else None,
            verification_notes="Confirmed attendance and progress. Verified plaster quality."
            if u["status"] == "verified"
            else None,
        )
        session.add(update)
        created += 1
    print(f"Seeded supervisor updates: {created}")


async def seed_photos(
    session, user_by_email: dict, project_objects: dict
) -> None:
    ensure_seed_storage_objects(SEED_PHOTO_OBJECTS)
    engineer = user_by_email.get("engineer.test@garrisons.lk")
    supervisor = user_by_email.get("supervisor.test@garrisons.lk")
    gip001 = project_objects.get("GIP-001")
    if not gip001:
        return

    report = await session.scalar(
        select(DailyReport).where(
            DailyReport.project_id == gip001.id,
            DailyReport.report_number == "DR-GIP-001-SEED-002",
            DailyReport.deleted_at.is_(None),
        )
    )
    update = await session.scalar(
        select(SupervisorUpdate).where(
            SupervisorUpdate.project_id == gip001.id,
            SupervisorUpdate.update_date == date.today() - timedelta(days=3),
            SupervisorUpdate.deleted_at.is_(None),
        )
    )

    if not engineer:
        return

    photos = [
        {
            "filename": "seed_site_overview.jpg",
            "original_name": "GIP001_site_overview.jpg",
            "storage_path": "seed-photos/site_overview.jpg",
            "compressed_path": "seed-photos/site_overview_compressed.jpg",
            "thumbnail_path": "seed-photos/site_overview_thumb.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 204800,
            "width": 1920,
            "height": 1080,
            "entity_type": "project",
            "entity_id": gip001.id,
            "kind": "photo",
            "caption": "Site overview - Lusail Villa A",
            "taken_at": datetime.now(UTC) - timedelta(days=10),
            "uploaded_by": engineer.id,
        },
        {
            "filename": "seed_blockwork_progress.jpg",
            "original_name": "blockwork_day5.jpg",
            "storage_path": "seed-photos/blockwork_day5.jpg",
            "compressed_path": "seed-photos/blockwork_day5_compressed.jpg",
            "thumbnail_path": "seed-photos/blockwork_day5_thumb.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 156000,
            "width": 1200,
            "height": 900,
            "entity_type": "supervisor_update" if update else "project",
            "entity_id": update.id if update else gip001.id,
            "kind": "photo",
            "caption": "Blockwork progress - Day 5",
            "taken_at": datetime.now(UTC) - timedelta(days=5),
            "uploaded_by": supervisor.id if supervisor else engineer.id,
        },
        {
            "filename": "seed_plaster_quality.pdf",
            "original_name": "plaster_check.pdf",
            "storage_path": "seed-attachments/plaster_check.pdf",
            "compressed_path": None,
            "thumbnail_path": None,
            "mime_type": "application/pdf",
            "size_bytes": 132000,
            "width": None,
            "height": None,
            "entity_type": "daily_report" if report else "project",
            "entity_id": report.id if report else gip001.id,
            "kind": "attachment",
            "caption": "Plaster quality check - Wall A3",
            "taken_at": datetime.now(UTC) - timedelta(days=2),
            "uploaded_by": engineer.id,
        },
    ]
    created = 0
    for photo_data in photos:
        photo = await session.scalar(
            select(Photo).where(
                Photo.filename == photo_data["filename"],
                Photo.deleted_at.is_(None),
            )
        )
        if not photo:
            session.add(Photo(**photo_data))
            created += 1
            continue
        for key, value in photo_data.items():
            setattr(photo, key, value)
    print(f"Seeded photos: {created} created, {len(photos) - created} updated")


async def seed_documents(
    session, user_by_email: dict, project_objects: dict
) -> None:
    ensure_seed_storage_objects(SEED_DOCUMENT_OBJECTS)
    pm = user_by_email.get("pm.test@garrisons.lk")
    engineer = user_by_email.get("engineer.test@garrisons.lk")
    ops = user_by_email.get("operations.test@garrisons.lk")
    gip001 = project_objects.get("GIP-001")
    if not pm or not gip001:
        return

    async def upsert_document(
        *,
        title: str,
        document_type: str,
        status: str,
        active_version: int | None,
        metadata_json: dict,
        expiry_date: date | None,
        versions: list[dict],
    ) -> bool:
        document = await session.scalar(
            select(Document).where(
                Document.project_id == gip001.id,
                Document.title == title,
                Document.deleted_at.is_(None),
            )
        )
        created = False
        if not document:
            document = Document(
                title=title,
                document_type=document_type,
                project_id=gip001.id,
                status=status,
                active_version=active_version,
                metadata_json=metadata_json,
                expiry_date=expiry_date,
                uploaded_by=pm.id,
            )
            session.add(document)
            await session.flush()
            created = True
        else:
            document.document_type = document_type
            document.status = status
            document.active_version = active_version
            document.metadata_json = metadata_json
            document.expiry_date = expiry_date

        for version_data in versions:
            version = await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.version == version_data["version"],
                    DocumentVersion.deleted_at.is_(None),
                )
            )
            if not version:
                session.add(
                    DocumentVersion(
                        document_id=document.id,
                        version=version_data["version"],
                        status=version_data["status"],
                        storage_path=version_data["storage_path"],
                        original_name=version_data["original_name"],
                        mime_type=version_data["mime_type"],
                        size_bytes=version_data["size_bytes"],
                        uploaded_by=version_data.get("uploaded_by", pm.id),
                        approved_by=version_data.get("approved_by"),
                        approved_at=version_data.get("approved_at"),
                        approval_comments=version_data.get("approval_comments"),
                    )
                )
                created = True
                continue
            version.status = version_data["status"]
            version.storage_path = version_data["storage_path"]
            version.original_name = version_data["original_name"]
            version.mime_type = version_data["mime_type"]
            version.size_bytes = version_data["size_bytes"]
            version.uploaded_by = version_data.get("uploaded_by", pm.id)
            version.approved_by = version_data.get("approved_by")
            version.approved_at = version_data.get("approved_at")
            version.approval_comments = version_data.get("approval_comments")
        return created

    now = datetime.now(UTC)
    created_count = 0
    specs = [
        {
            "title": "Project Execution Plan",
            "document_type": "drawing",
            "status": "active",
            "active_version": 2,
            "metadata_json": {
                "author": "Project Manager",
                "department": "Civil",
                "document_number": "GIP-001-DWG-CIV-2026-001-REV-B",
                "tags": ["execution", "drawing", "superseded-warning"],
            },
            "expiry_date": None,
            "versions": [
                {
                    "version": 1,
                    "status": "superseded",
                    "storage_path": "seed-docs/pep_v1.pdf",
                    "original_name": "PEP_Lusail_Villa_v1.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 512000,
                    "approved_by": ops.id if ops else None,
                    "approved_at": now - timedelta(days=20),
                    "approval_comments": "Approved with minor comments",
                },
                {
                    "version": 2,
                    "status": "active",
                    "storage_path": "seed-docs/pep_v2.pdf",
                    "original_name": "PEP_Lusail_Villa_v2.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 545000,
                    "approved_by": ops.id if ops else None,
                    "approved_at": now - timedelta(days=5),
                    "approval_comments": "Revision approved - all comments addressed",
                },
            ],
        },
        {
            "title": "MAR Cement Mix Design",
            "document_type": "mar",
            "status": "pending_approval",
            "active_version": None,
            "metadata_json": {
                "author": "Civil Engineer",
                "department": "Quality",
                "document_number": "GIP-001-MAR-CIV-2026-001-REV-A",
                "tags": ["MAR", "cement", "pending"],
            },
            "expiry_date": date.today() + timedelta(days=180),
            "versions": [
                {
                    "version": 1,
                    "status": "pending_approval",
                    "storage_path": "seed-docs/mar_cement_mix_design.pdf",
                    "original_name": "MAR_Cement_Mix_Design_REV_A.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 260000,
                    "uploaded_by": engineer.id if engineer else pm.id,
                },
            ],
        },
        {
            "title": "MIR Steel Rebar Delivery",
            "document_type": "mir",
            "status": "active",
            "active_version": 1,
            "metadata_json": {
                "author": "Civil Engineer",
                "department": "Quality",
                "document_number": "GIP-001-MIR-CIV-2026-002-REV-A",
                "tags": ["MIR", "steel", "approved"],
            },
            "expiry_date": None,
            "versions": [
                {
                    "version": 1,
                    "status": "active",
                    "storage_path": "seed-docs/mir_steel_rebar_delivery.pdf",
                    "original_name": "MIR_Steel_Rebar_Delivery_REV_A.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 225000,
                    "uploaded_by": engineer.id if engineer else pm.id,
                    "approved_by": pm.id,
                    "approved_at": now - timedelta(days=6),
                    "approval_comments": "Material inspection passed.",
                },
            ],
        },
        {
            "title": "WIR Plaster Inspection Zone A",
            "document_type": "wir",
            "status": "active",
            "active_version": 1,
            "metadata_json": {
                "author": "Civil Engineer",
                "department": "Quality",
                "document_number": "GIP-001-WIR-CIV-2026-003-REV-A",
                "tags": ["WIR", "inspection", "approved"],
            },
            "expiry_date": None,
            "versions": [
                {
                    "version": 1,
                    "status": "active",
                    "storage_path": "seed-docs/wir_plaster_zone_a.pdf",
                    "original_name": "WIR_Plaster_Zone_A_REV_A.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 190000,
                    "uploaded_by": engineer.id if engineer else pm.id,
                    "approved_by": pm.id,
                    "approved_at": now - timedelta(days=2),
                    "approval_comments": "Inspection accepted.",
                },
            ],
        },
        {
            "title": "Delivery Note Cement Batch 001",
            "document_type": "delivery_note",
            "status": "active",
            "active_version": 1,
            "metadata_json": {
                "author": "Store Keeper",
                "department": "Store",
                "document_number": "GIP-001-DLN-CIV-2026-004-REV-A",
                "tags": ["delivery note", "cement", "approved"],
            },
            "expiry_date": None,
            "versions": [
                {
                    "version": 1,
                    "status": "active",
                    "storage_path": "seed-docs/delivery_note_cement_batch001.pdf",
                    "original_name": "Delivery_Note_Cement_Batch001.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 160000,
                    "approved_by": pm.id,
                    "approved_at": now - timedelta(days=9),
                    "approval_comments": "Matched delivery note and PO.",
                },
            ],
        },
    ]
    for spec in specs:
        if await upsert_document(**spec):
            created_count += 1
    print(
        "Seeded documents: "
        f"{created_count} created or expanded, {len(specs) - created_count} updated"
    )


async def seed_daily_reports(
    session, user_by_email: dict, project_objects: dict
) -> None:
    engineer = user_by_email.get("engineer.test@garrisons.lk")
    project = project_objects.get("GIP-001")
    if not engineer or not project:
        return

    reports = [
        {
            "report_number": "DR-GIP-001-SEED",
            "report_date": date.today(),
            "work_location": "Villa A - Ground Floor",
            "manpower_total": 18,
            "overtime_hours": Decimal("6.00"),
            "work_completed": "Completed blockwork alignment and started plaster preparation.",
            "progress_percentage": Decimal("36.00"),
            "safety_incidents": 0,
            "safety_notes": "Toolbox talk completed before site start.",
            "wir_status": "pending",
            "inspection_status": "not_requested",
            "delay_notes": None,
            "next_day_plan": "Continue internal plaster and coordinate material delivery.",
            "status": "submitted",
            "extra_fields": {
                "day_type": "weekday",
                "weather_condition": "Sunny",
                "site_visitors": "Client representative - 1, consultant engineer - 1",
                "subcontractors": "Blockwork subcontractor crew",
                "wir_number": "GIP-001-WIR-CIV-2026-001",
            },
            "manpower": [
                ("Mason", 8, Decimal("2.00")),
                ("Helper", 10, Decimal("4.00")),
            ],
            "equipment": [
                ("Concrete Mixer", 1, Decimal("5.00"), "Shared with plaster team"),
            ],
            "materials": [
                ("Cement", "bag", Decimal("42.000"), "Issued from site store"),
            ],
        },
        {
            "report_number": "DR-GIP-001-SEED-002",
            "report_date": date.today() - timedelta(days=1),
            "work_location": "Villa A - Ground Floor & First Floor",
            "manpower_total": 22,
            "overtime_hours": Decimal("8.00"),
            "work_completed": (
                "Plaster scratch coat completed in Ground Floor rooms. "
                "First floor blockwork 60% complete."
            ),
            "progress_percentage": Decimal("38.00"),
            "safety_incidents": 0,
            "safety_notes": "Daily PPE inspection passed. All workers equipped.",
            "wir_status": "submitted",
            "inspection_status": "requested",
            "delay_notes": None,
            "next_day_plan": "Complete first floor blockwork. Begin plaster on first floor.",
            "status": "approved",
            "extra_fields": {
                "day_type": "weekday",
                "weather_condition": "Cloudy",
                "site_visitors": "Consultant engineer - 1",
                "subcontractors": "MEP first-fix crew, plaster crew",
                "wir_number": "GIP-001-WIR-CIV-2026-002",
            },
            "manpower": [
                ("Mason", 10, Decimal("3.00")),
                ("Helper", 10, Decimal("4.00")),
                ("Electrician", 2, Decimal("1.00")),
            ],
            "equipment": [
                ("Concrete Mixer", 2, Decimal("6.00"), "Both mixers operational"),
                ("Scaffolding Set", 3, Decimal("8.00"), "First floor access"),
            ],
            "materials": [
                ("Cement", "bag", Decimal("50.000"), "For plaster and blockwork"),
                ("Sand", "m3", Decimal("3.500"), "For plaster mix"),
            ],
        },
        {
            "report_number": "DR-GIP-001-SEED-003",
            "report_date": date.today() - timedelta(days=3),
            "work_location": "Villa A - Ground Floor",
            "manpower_total": 15,
            "overtime_hours": Decimal("4.00"),
            "work_completed": "Ground floor blockwork layout and first course laid.",
            "progress_percentage": Decimal("32.00"),
            "safety_incidents": 1,
            "safety_notes": (
                "Minor hand injury - worker treated on site. "
                "Near-miss report filed for falling debris."
            ),
            "wir_status": "draft",
            "inspection_status": "not_requested",
            "delay_notes": "Delayed start due to material delivery waiting — 1 hour lost.",
            "next_day_plan": "Continue blockwork. Expedite cement delivery.",
            "status": "rejected",
            "extra_fields": {
                "day_type": "weekday",
                "weather_condition": "Dusty",
                "site_visitors": "None",
                "subcontractors": "Blockwork subcontractor crew",
                "wir_number": "Not required",
            },
            "manpower": [
                ("Mason", 6, Decimal("2.00")),
                ("Helper", 9, Decimal("2.00")),
            ],
            "equipment": [
                ("Concrete Mixer", 1, Decimal("4.00"), ""),
            ],
            "materials": [
                ("Cement", "bag", Decimal("30.000"), ""),
                ("Blocks 200mm", "piece", Decimal("450.000"), ""),
            ],
        },
    ]

    for r in reports:
        existing = await session.scalar(
            select(DailyReport).where(
                DailyReport.project_id == project.id,
                DailyReport.report_number == r["report_number"],
                DailyReport.deleted_at.is_(None),
            )
        )
        if existing:
            existing.extra_fields = {
                **(existing.extra_fields or {}),
                "seed_data": True,
                "uat_scenario": r["status"],
                **r["extra_fields"],
            }
            continue
        report = DailyReport(
            project_id=project.id,
            engineer_id=engineer.id,
            report_number=r["report_number"],
            report_date=r["report_date"],
            work_location=r["work_location"],
            manpower_total=r["manpower_total"],
            overtime_hours=r["overtime_hours"],
            work_completed=r["work_completed"],
            progress_percentage=r["progress_percentage"],
            safety_incidents=r["safety_incidents"],
            safety_notes=r["safety_notes"],
            wir_status=r["wir_status"],
            inspection_status=r["inspection_status"],
            delay_notes=r["delay_notes"],
            next_day_plan=r["next_day_plan"],
            supervisor_update_ids=[],
            photo_refs=[],
            attachment_refs=[],
            status=r["status"],
            extra_fields={
                "seed_data": True,
                "uat_scenario": r["status"],
                **r["extra_fields"],
            },
        )
        report.manpower_entries = [
            ReportManpower(trade=t, count=c, overtime_hours=o)
            for t, c, o in r["manpower"]
        ]
        report.equipment_entries = [
            ReportEquipment(
                equipment_name=e, quantity=q, hours_used=h, remarks=rm
            )
            for e, q, h, rm in r["equipment"]
        ]
        report.material_consumption = [
            ReportMaterialConsumption(
                material_name=m, unit=u, quantity=q, remarks=rm
            )
            for m, u, q, rm in r["materials"]
        ]
        session.add(report)
    print("Seeded daily reports: submitted, approved, rejected")


async def seed_approvals(
    session, user_by_email: dict, project_objects: dict
) -> None:
    engineer = user_by_email.get("engineer.test@garrisons.lk")
    pm = user_by_email.get("pm.test@garrisons.lk")
    ops = user_by_email.get("operations.test@garrisons.lk")
    gip001 = project_objects.get("GIP-001")
    if not gip001:
        return

    report = await session.scalar(
        select(DailyReport).where(
            DailyReport.project_id == gip001.id,
            DailyReport.report_number == "DR-GIP-001-SEED",
            DailyReport.deleted_at.is_(None),
        )
    )
    now = datetime.now(UTC)

    if report and engineer and not await session.scalar(
        select(Approval).where(
            Approval.request_type == "daily_report",
            Approval.request_id == report.id,
            Approval.deleted_at.is_(None),
        )
    ):
        session.add(
            Approval(
                request_type="daily_report",
                request_id=report.id,
                project_id=gip001.id,
                submitter_id=engineer.id,
                approver_id=pm.id if pm else None,
                status="pending",
                step_order=1,
                title="Daily Report Approval — DR-GIP-001-SEED",
                submitter_comments="Daily report for today's blockwork and plaster preparation.",
                submitted_at=now - timedelta(hours=4),
                due_at=now + timedelta(hours=20),
            )
        )

    report2 = await session.scalar(
        select(DailyReport).where(
            DailyReport.project_id == gip001.id,
            DailyReport.report_number == "DR-GIP-001-SEED-002",
            DailyReport.deleted_at.is_(None),
        )
    )
    if report2 and pm and not await session.scalar(
        select(Approval).where(
            Approval.request_type == "daily_report",
            Approval.request_id == report2.id,
            Approval.deleted_at.is_(None),
        )
    ):
        session.add(
            Approval(
                request_type="daily_report",
                request_id=report2.id,
                project_id=gip001.id,
                submitter_id=engineer.id if engineer else None,
                approver_id=pm.id,
                status="approved",
                step_order=1,
                title="Daily Report Approval — DR-GIP-001-SEED-002",
                submitter_comments="Report for yesterday's work.",
                decision_comments="Good progress. Approved.",
                submitted_at=now - timedelta(days=1),
                due_at=now - timedelta(hours=20),
                decided_at=now - timedelta(hours=20),
            )
        )

    if ops and pm and not await session.scalar(
        select(Approval).where(
            Approval.request_type == "project_budget",
            Approval.project_id == gip001.id,
            Approval.title == "Budget Revision — Additional MEP Scope",
            Approval.deleted_at.is_(None),
        )
    ):
        session.add(
            Approval(
                request_type="project_budget",
                request_id=gip001.id,
                project_id=gip001.id,
                submitter_id=pm.id,
                approver_id=ops.id,
                status="pending",
                step_order=1,
                amount=Decimal("85000.00"),
                currency="QAR",
                title="Budget Revision — Additional MEP Scope",
                submitter_comments=(
                    "Client requested additional MEP scope - requires budget increase of "
                    "QAR 85,000."
                ),
                submitted_at=now - timedelta(hours=2),
                due_at=now + timedelta(days=2),
            )
        )
    print("Seeded approvals: daily report + budget revision")


async def seed_notifications(
    session, user_by_email: dict, project_objects: dict
) -> None:
    now = datetime.now(UTC)
    notifications = [
        {
            "user_email": DEFAULT_ADMIN_EMAIL,
            "title": "Daily Report Submitted",
            "body": "Engineer submitted daily report DR-GIP-001-SEED for Lusail Villa Fit-Out.",
            "notification_type": "report_submitted",
            "reference_type": "daily_report",
            "is_read": False,
        },
        {
            "user_email": DEFAULT_ADMIN_EMAIL,
            "title": "Low Stock Alert",
            "body": (
                "Safety Helmets at GIP-001 Site Store dropped below reorder level "
                "(40 remaining, reorder at 50)."
            ),
            "notification_type": "low_stock",
            "reference_type": "inventory",
            "is_read": False,
        },
        {
            "user_email": "pm.test@garrisons.lk",
            "title": "Daily Report Submitted",
            "body": "Engineer submitted daily report DR-GIP-001-SEED for Lusail Villa Fit-Out.",
            "notification_type": "report_submitted",
            "reference_type": "daily_report",
            "is_read": False,
        },
        {
            "user_email": "pm.test@garrisons.lk",
            "title": "Budget Revision Requested",
            "body": "A budget revision of QAR 85,000 has been requested for Lusail Villa Fit-Out.",
            "notification_type": "approval_requested",
            "reference_type": "approval",
            "is_read": True,
        },
        {
            "user_email": "engineer.test@garrisons.lk",
            "title": "Report Approved",
            "body": "Your daily report DR-GIP-001-SEED-002 has been approved.",
            "notification_type": "report_approved",
            "reference_type": "daily_report",
            "is_read": True,
        },
        {
            "user_email": "engineer.test@garrisons.lk",
            "title": "Report Rejected",
            "body": (
                "Your daily report DR-GIP-001-SEED-003 was rejected. "
                "Please review comments and resubmit."
            ),
            "notification_type": "report_rejected",
            "reference_type": "daily_report",
            "is_read": False,
        },
        {
            "user_email": "storekeeper.test@garrisons.lk",
            "title": "Low Stock Alert",
            "body": (
                "Safety Helmets at GIP-001 Site Store dropped below reorder level "
                "(40 remaining, reorder at 50)."
            ),
            "notification_type": "low_stock",
            "reference_type": "inventory",
            "is_read": False,
        },
        {
            "user_email": "supervisor.test@garrisons.lk",
            "title": "Supervisor Update Verified",
            "body": "Your site update from 3 days ago has been verified by the engineer.",
            "notification_type": "update_verified",
            "reference_type": "supervisor_update",
            "is_read": True,
        },
        {
            "user_email": "accounts.test@garrisons.lk",
            "title": "Invoice Due Soon",
            "body": "Invoice INV-GIP001-SEED-001 (QAR 23,625) is due in 15 days.",
            "notification_type": "invoice_due",
            "reference_type": "invoice",
            "is_read": False,
        },
    ]
    created = 0
    for n in notifications:
        user = user_by_email.get(n["user_email"])
        if not user:
            continue
        existing = await session.scalar(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.title == n["title"],
                Notification.deleted_at.is_(None),
            )
        )
        if existing:
            continue
        session.add(
            Notification(
                user_id=user.id,
                title=n["title"],
                body=n["body"],
                notification_type=n["notification_type"],
                reference_type=n["reference_type"],
                is_read=n["is_read"],
                email_status="sent",
                read_at=now - timedelta(hours=1) if n["is_read"] else None,
            )
        )
        created += 1
    print(f"Seeded notifications: {created}")


async def seed_activity_logs(
    session, user_by_email: dict, project_objects: dict
) -> None:
    admin = user_by_email.get(DEFAULT_ADMIN_EMAIL)
    engineer = user_by_email.get("engineer.test@garrisons.lk")
    pm = user_by_email.get("pm.test@garrisons.lk")
    store = user_by_email.get("storekeeper.test@garrisons.lk")
    if not admin:
        return
    now = datetime.now(UTC)
    logs = [
        ActivityLog(
            user_id=admin.id,
            action="user_login",
            entity_type="user",
            ip_address="10.0.0.1",
            comments="Admin login from office IP",
            created_at=now - timedelta(hours=6),
        ),
        ActivityLog(
            user_id=engineer.id if engineer else admin.id,
            action="report_create",
            entity_type="daily_report",
            comments="Created daily report DR-GIP-001-SEED",
            created_at=now - timedelta(hours=5),
        ),
        ActivityLog(
            user_id=engineer.id if engineer else admin.id,
            action="report_submit",
            entity_type="daily_report",
            comments="Submitted daily report for approval",
            created_at=now - timedelta(hours=4),
        ),
        ActivityLog(
            user_id=pm.id if pm else admin.id,
            action="approval_decision",
            entity_type="approval",
            comments="Approved daily report DR-GIP-001-SEED-002",
            old_values={"status": "pending"},
            new_values={"status": "approved"},
            created_at=now - timedelta(hours=20),
        ),
        ActivityLog(
            user_id=store.id if store else admin.id,
            action="inventory_movement",
            entity_type="inventory",
            comments="Transferred 200 bags cement from warehouse to GIP-001 site store",
            created_at=now - timedelta(days=7),
        ),
        ActivityLog(
            user_id=admin.id,
            action="seed_data",
            entity_type="system",
            comments="Seed data loaded for UAT environment",
            created_at=now - timedelta(seconds=10),
        ),
    ]
    created = 0
    for log in logs:
        existing = await session.scalar(
            select(ActivityLog).where(
                ActivityLog.action == log.action,
                ActivityLog.entity_type == log.entity_type,
                ActivityLog.comments == log.comments,
                ActivityLog.deleted_at.is_(None),
            )
        )
        if existing:
            continue
        session.add(log)
        created += 1
    print(f"Seeded activity logs: {created} created, {len(logs) - created} existing")


async def seed_report_exports(
    session, user_by_email: dict, project_objects: dict
) -> None:
    gip001 = project_objects.get("GIP-001")
    if not gip001:
        return
    report = await session.scalar(
        select(DailyReport).where(
            DailyReport.project_id == gip001.id,
            DailyReport.report_number == "DR-GIP-001-SEED-002",
            DailyReport.deleted_at.is_(None),
        )
    )
    if not report:
        return
    existing = await session.scalar(
        select(ReportExport).where(
            ReportExport.report_id == report.id,
            ReportExport.deleted_at.is_(None),
        )
    )
    if existing:
        print("Seeded report exports: 0 (already exist)")
        return

    pm = user_by_email.get("pm.test@garrisons.lk")
    now = datetime.now(UTC)
    session.add(
        ReportExport(
            report_id=report.id,
            generated_by=pm.id if pm else None,
            file_name="DR-GIP-001-SEED-002.pdf",
            object_key="seed-exports/DR-GIP-001-SEED-002.pdf",
            content_type="application/pdf",
            status="ready",
            email_status="sent",
            emailed_at=now - timedelta(hours=18),
            generated_at=now - timedelta(hours=19),
        )
    )
    print("Seeded report exports: 1")


async def seed_import_batches(session, user_by_email: dict) -> None:
    admin = user_by_email.get(DEFAULT_ADMIN_EMAIL)
    if not admin:
        return
    existing = await session.scalar(
        select(ImportBatch).where(
            ImportBatch.template_type == "boq",
            ImportBatch.file_name == "seed_boq_import.xlsx",
            ImportBatch.deleted_at.is_(None),
        )
    )
    if existing:
        print("Seeded import batches: 0 (already exist)")
        return
    session.add(
        ImportBatch(
            template_type="boq",
            file_name="seed_boq_import.xlsx",
            status="completed",
            created_by=admin.id,
            row_count=5,
            error_count=0,
            summary={"imported": 5, "skipped": 0, "errors": []},
            created_at=datetime.now(UTC) - timedelta(days=10),
        )
    )
    session.add(
        ImportBatch(
            template_type="supplier",
            file_name="seed_supplier_import.csv",
            status="partial",
            created_by=admin.id,
            row_count=10,
            error_count=2,
            summary={
                "imported": 8,
                "skipped": 0,
                "errors": [
                    {"row": 4, "reason": "Duplicate email"},
                    {"row": 9, "reason": "Missing tax registration number"},
                ],
            },
            created_at=datetime.now(UTC) - timedelta(days=8),
        )
    )
    print("Seeded import batches: 2")


def main() -> None:
    asyncio.run(seed_launch_data())


if __name__ == "__main__":
    main()
