"""Preview audit retention deadlines without modifying event records."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import func, select, text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.activity_log import ActivityLog
from app.services.audit_service import AuditService


async def preview() -> None:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            service = AuditService(session)
            candidates = await service.preview_purge()
            missing = await session.scalar(select(func.count(ActivityLog.id)).where(
                ActivityLog.deleted_at.is_(None), ActivityLog.retention_until.is_(None),
            ))
            print(json.dumps({
                "archive_retention_days": service.settings.log_archive_retention_days,
                "purge_enabled": service.settings.log_purge_enabled,
                "missing_deadlines": missing,
                "candidate_batch": [
                    {"id": str(event_id), "retention_until": deadline.isoformat()}
                    for event_id, deadline in candidates
                ],
            }))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-understand", action="store_true")
    args = parser.parse_args()
    if get_settings().app_env.lower() == "production" and not args.i_understand:
        parser.error("Authorized production operators must pass --i-understand.")
    asyncio.run(preview())


if __name__ == "__main__":
    main()
