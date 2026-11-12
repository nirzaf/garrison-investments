"""Report possible offline draft duplicates and consolidate a reviewed pair."""

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.daily_report import DailyReport
from app.models.idempotency_record import IdempotencyRecord
from app.models.photo import Photo
from app.schemas.daily_reports import DailyReportResponse
from app.services.audit_service import AuditService
from app.services.photo_service import MAX_REPORT_PHOTOS
from app.utils.security import utc_now

WINDOW = timedelta(seconds=120)


async def report_candidates(session: AsyncSession) -> None:
    report = DailyReport
    grouping = (report.project_id, report.report_date, report.engineer_id, report.work_completed)
    query = (
        select(*grouping, report.created_at, report.id)
        .where(
            report.status == "draft",
            report.report_number.is_(None),
            report.deleted_at.is_(None),
        )
        .order_by(*grouping, report.created_at, report.id)
    )
    first = None
    async for row in await session.stream(query):
        if first is None or row[:4] != first[:4] or row.created_at - first.created_at > WINDOW:
            first = row
            continue
        print(
            json.dumps(
                {
                    "keep": str(first.id),
                    "candidate": str(row.id),
                    "project_id": str(row.project_id),
                    "report_date": row.report_date.isoformat(),
                    "seconds_apart": (row.created_at - first.created_at).total_seconds(),
                }
            )
        )


async def consolidate_pair(session: AsyncSession, keep: UUID, duplicate: UUID) -> None:
    rows = list(
        await session.scalars(
            select(DailyReport)
            .where(DailyReport.id.in_([keep, duplicate]), DailyReport.deleted_at.is_(None))
            .order_by(DailyReport.created_at, DailyReport.id)
            .with_for_update()
        )
    )
    if len(rows) != 2 or [row.id for row in rows] != [keep, duplicate]:
        raise ValueError("Both live drafts must exist and --keep must identify the earlier draft.")
    if rows[1].created_at - rows[0].created_at > WINDOW:
        raise ValueError("The drafts were created more than 120 seconds apart.")
    if any(
        row.status != "draft" or row.report_number is not None or row.approval_history
        for row in rows
    ):
        raise ValueError("Both reports must be unnumbered drafts without approval history.")
    first, second = (
        DailyReportResponse.model_validate(row).model_dump(
            exclude={
                "id": True,
                "revision": True,
                "manpower_entries": {"__all__": {"id"}},
                "equipment_entries": {"__all__": {"id"}},
                "material_consumption": {"__all__": {"id"}},
            }
        )
        for row in rows
    )
    if first != second:
        raise ValueError("Draft contents differ. Review and resolve them manually.")
    # Both parents are locked, so uploads and recovery cannot change this count.
    active_photos = await session.scalar(
        select(func.count(Photo.id)).where(
            Photo.entity_type == "daily_report",
            Photo.entity_id.in_([keep, duplicate]),
            Photo.kind == "photo",
            Photo.deleted_at.is_(None),
        )
    )
    if (active_photos or 0) > MAX_REPORT_PHOTOS:
        raise ValueError(f"The consolidated report would exceed {MAX_REPORT_PHOTOS} active photos.")
    await session.execute(
        update(Photo)
        .where(Photo.entity_type == "daily_report", Photo.entity_id == duplicate)
        .values(entity_id=keep, report_revision=None)
    )
    await session.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.resource_type == "daily_report",
            IdempotencyRecord.resource_id == duplicate,
        )
        .values(resource_id=keep)
    )
    rows[0].revision += 1
    rows[1].deleted_at = utc_now()
    await AuditService(session).record(
        action="daily_reports.offline_duplicate_consolidated",
        entity_type="daily_reports",
        entity_id=keep,
        context_payload={"duplicate_id": str(duplicate)},
    )
    await session.commit()
    print(json.dumps({"kept": str(keep), "consolidated": str(duplicate)}))


async def run(keep: UUID | None, duplicate: UUID | None) -> None:
    try:
        async with AsyncSessionLocal() as session:
            if keep and duplicate:
                await consolidate_pair(session, keep, duplicate)
            else:
                await session.execute(text("SET TRANSACTION READ ONLY"))
                await report_candidates(session)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Consolidate one reviewed pair.")
    parser.add_argument("--keep", type=UUID, help="UUID of the earliest draft in the pair.")
    parser.add_argument("--duplicate", type=UUID, help="UUID of the duplicate draft.")
    parser.add_argument("--i-understand", action="store_true", help="Allow production access.")
    args = parser.parse_args()
    if get_settings().app_env.lower() == "production" and not args.i_understand:
        parser.error("Production access requires --i-understand.")
    if args.apply:
        if not args.keep or not args.duplicate or args.keep == args.duplicate:
            parser.error("--apply requires distinct --keep and --duplicate UUIDs.")
    elif args.keep or args.duplicate:
        parser.error("--keep and --duplicate require --apply.")
    try:
        asyncio.run(run(args.keep, args.duplicate))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
