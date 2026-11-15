"""Generate demo daily reports for all active projects in a development database.

Run from the backend directory:
    python scripts/dev/generate_missing_reports.py --fabricate-demo-data

Targets 2026-05-28 (the date flagged as missing by check_late_reports).
"""

import argparse
import asyncio
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from random import choice, randint

sys.path.append(str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.daily_report import (
    DailyReport,
    ReportEquipment,
    ReportManpower,
    ReportMaterialConsumption,
)
from app.models.project import Project
from app.models.user import User

REPORT_DATE = date(2026, 5, 28)

WORK_LOCATIONS = [
    "Ground Floor - Block A",
    "First Floor - Block B",
    "Site Entrance Area",
    "Main Building - Level 2",
    "Warehouse Zone",
    "Service Yard",
    "Roof Level",
    "Basement Parking",
]

WORK_COMPLETED = [
    "Completed blockwork alignment and started plaster preparation on all elevations.",
    "MEP first-fix conduit laying completed in corridors. Ceiling grid installation started.",
    "Excavation and backfilling for underground services completed. Compaction tested.",
    "Waterproofing application on roof slab completed. Curing started.",
    "Steel reinforcement for retaining wall completed. Formwork erection in progress.",
    "Tile flooring installation 70% complete in common areas. Skirting work ongoing.",
    "HVAC duct installation completed on first floor. Testing scheduled for tomorrow.",
    "External cladding panels installed on east elevation. Sealant application pending.",
]

NEXT_DAY_PLANS = [
    "Continue internal plaster and coordinate material delivery for next phase.",
    "Complete ceiling grid installation. Begin painting primer coat.",
    "Start formwork for next pour. Rebar inspection scheduled.",
    "Proceed with floor tiling. Begin electrical conduit pulling.",
    "Complete waterproofing curing. Prepare for screed application.",
    "Continue external cladding. Schedule consultant inspection.",
    "Begin MEP second-fix in completed zones. Continue duct testing.",
    "Resume blockwork on upper level. Coordinate scaffold erection.",
]

TRADES = [
    ("Mason", (6, 12)),
    ("Helper", (8, 15)),
    ("Electrician", (2, 5)),
    ("Plumber", (2, 4)),
    ("Painter", (3, 6)),
    ("Steel Fixer", (4, 8)),
    ("Carpenter", (3, 6)),
    ("Tile Mason", (2, 5)),
]

EQUIPMENT = [
    ("Concrete Mixer", (1, 3)),
    ("Scaffolding Set", (2, 6)),
    ("Tower Crane", (1, 1)),
    ("Generator 100kVA", (1, 2)),
    ("Vibratory Roller", (1, 1)),
    ("Excavator", (1, 2)),
    ("Welding Machine", (2, 4)),
]

MATERIALS = [
    ("Cement", "bag", (20, 60)),
    ("Sand", "m3", (2, 8)),
    ("Blocks 200mm", "piece", (200, 600)),
    ("Steel Rebar 12mm", "ton", (1, 4)),
    ("PVC Conduit 25mm", "piece", (50, 200)),
    ("Ready Mix Concrete", "m3", (5, 20)),
    ("Waterproofing Membrane", "roll", (3, 10)),
]

WIR_STATUSES = ["pending", "submitted", "approved", "draft", "not_required"]
INSPECTION_STATUSES = ["not_requested", "requested", "passed", "failed"]
WEATHER = ["Sunny", "Cloudy", "Hot & Humid", "Dusty", "Clear", "Overcast"]


def _random_manpower():
    n = randint(2, 4)
    selected = [(t, lo, hi) for t, lo, hi in TRADES[:n]]
    return [(t, randint(lo, hi), Decimal(f"{randint(0, 4)}.00")) for t, lo, hi in selected]


def _random_equipment():
    n = randint(1, 3)
    selected = [(e, lo, hi) for e, lo, hi in EQUIPMENT[:n]]
    return [(e, randint(lo, hi), Decimal(f"{randint(4, 10)}.00"), "") for e, lo, hi in selected]


def _random_materials():
    n = randint(1, 3)
    selected = [(m, u, lo, hi) for m, u, lo, hi in MATERIALS[:n]]
    return [(m, u, Decimal(f"{randint(lo, hi)}.000"), "") for m, u, lo, hi in selected]


async def main():
    if get_settings().app_env.strip().lower() not in {"development", "local", "test"}:
        raise SystemExit("Demo report generation is restricted to development, local, and test.")
    async with AsyncSessionLocal() as session:
        # Fetch all active, non-deleted projects
        projects = (
            (
                await session.execute(
                    select(Project).where(Project.status == "active", Project.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )

        if not projects:
            print("No active projects found.")
            return

        # Fetch an engineer user to author the reports
        engineer = await session.scalar(
            select(User).where(User.role == "quantity_surveyor", User.deleted_at.is_(None))
        )
        if not engineer:
            # Fallback: use any active user
            engineer = await session.scalar(select(User).where(User.deleted_at.is_(None)))
        if not engineer:
            print("No users found to author reports.")
            return

        created = 0
        skipped = 0

        for project in projects:
            # Check if report already exists
            existing = await session.scalar(
                select(DailyReport.id).where(
                    DailyReport.project_id == project.id,
                    DailyReport.report_date == REPORT_DATE,
                    DailyReport.deleted_at.is_(None),
                )
            )
            if existing:
                print(f"  [skip] {project.code} — report already exists for {REPORT_DATE}")
                skipped += 1
                continue

            manpower_data = _random_manpower()
            equipment_data = _random_equipment()
            materials_data = _random_materials()
            total_manpower = sum(count for _, count, _ in manpower_data)

            report = DailyReport(
                project_id=project.id,
                engineer_id=engineer.id,
                report_date=REPORT_DATE,
                work_location=choice(WORK_LOCATIONS),
                manpower_total=total_manpower,
                overtime_hours=Decimal(f"{randint(2, 10)}.00"),
                work_completed=choice(WORK_COMPLETED),
                progress_percentage=Decimal(f"{randint(15, 85)}.00"),
                safety_incidents=0,
                safety_notes="Toolbox talk completed. All PPE inspected.",
                wir_status=choice(WIR_STATUSES),
                inspection_status=choice(INSPECTION_STATUSES),
                delay_notes=None,
                next_day_plan=choice(NEXT_DAY_PLANS),
                status="submitted",
                extra_fields={
                    "day_type": "weekday",
                    "weather_condition": choice(WEATHER),
                    "site_visitors": "Consultant engineer - 1",
                    "subcontractors": "General subcontractor crew",
                },
            )
            session.add(report)
            await session.flush()  # get report.id

            for trade, count, ot in manpower_data:
                session.add(
                    ReportManpower(
                        report_id=report.id,
                        trade=trade,
                        count=count,
                        overtime_hours=ot,
                    )
                )

            for eq_name, qty, hours, remarks in equipment_data:
                session.add(
                    ReportEquipment(
                        report_id=report.id,
                        equipment_name=eq_name,
                        quantity=qty,
                        hours_used=hours,
                        remarks=remarks,
                    )
                )

            for mat_name, unit, qty, remarks in materials_data:
                session.add(
                    ReportMaterialConsumption(
                        report_id=report.id,
                        material_name=mat_name,
                        unit=unit,
                        quantity=qty,
                        remarks=remarks,
                    )
                )

            print(f"  [created] {project.code} — report for {REPORT_DATE}")
            created += 1

        await session.commit()
        print(f"\nDone. Created: {created}, Skipped: {skipped}, Total projects: {len(projects)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fabricate-demo-data", action="store_true", required=True)
    parser.parse_args()
    asyncio.run(main())
