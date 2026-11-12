"""Preview audit retention deadlines without modifying event records."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select, text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.activity_log import ActivityLog
from app.services.audit_service import AuditService


async def preview(*, missing_limit: int = 100, missing_after: UUID | None = None) -> None:
    missing_deadline = (
        ActivityLog.deleted_at.is_(None),
        ActivityLog.retention_until.is_(None),
    )
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            service = AuditService(session)
            candidates = await service.preview_purge()
            missing = await session.scalar(
                select(func.count(ActivityLog.id)).where(*missing_deadline)
            )
            missing_query = (
                select(ActivityLog.id, ActivityLog.created_at, ActivityLog.storage_tier)
                .where(*missing_deadline)
                .order_by(ActivityLog.id)
                .limit(missing_limit + 1)
            )
            if missing_after is not None:
                missing_query = missing_query.where(ActivityLog.id > missing_after)
            rows = (await session.execute(missing_query)).all()
            page = rows[:missing_limit]
            print(
                json.dumps(
                    {
                        "archive_retention_days": service.settings.log_archive_retention_days,
                        "purge_enabled": service.settings.log_purge_enabled,
                        "missing_deadlines": missing,
                        "missing_deadline_batch": [
                            {
                                "id": str(row.id),
                                "created_at": row.created_at.isoformat(),
                                "storage_tier": row.storage_tier,
                                "reason": "missing_retention_deadline",
                                "proposed_disposition": "retain_pending_owner_review",
                            }
                            for row in page
                        ],
                        "next_missing_after": (
                            str(page[-1].id) if len(rows) > missing_limit else None
                        ),
                        "candidate_batch": [
                            {"id": str(event_id), "retention_until": deadline.isoformat()}
                            for event_id, deadline in candidates
                        ],
                    }
                )
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-understand", action="store_true")
    parser.add_argument(
        "--missing-limit", type=int, default=100, help="Missing-deadline rows per page (1–1000)."
    )
    parser.add_argument("--missing-after", type=UUID, help="Continue after a prior page cursor.")
    args = parser.parse_args()
    if not 1 <= args.missing_limit <= 1000:
        parser.error("--missing-limit must be between 1 and 1000.")
    if get_settings().app_env.lower() == "production" and not args.i_understand:
        parser.error("Authorized production operators must pass --i-understand.")
    asyncio.run(preview(missing_limit=args.missing_limit, missing_after=args.missing_after))


if __name__ == "__main__":
    main()
