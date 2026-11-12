"""Report owners whose active photos exceed the report media quota."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import func, select, text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.photo import Photo
from app.services.photo_service import MAX_REPORT_PHOTOS


async def report_drift() -> None:
    count = func.count(Photo.id)
    query = (
        select(Photo.entity_type, Photo.entity_id, count.label("active_photo_count"))
        .where(
            Photo.entity_type.in_(("daily_report", "supervisor_update")),
            Photo.kind == "photo",
            Photo.deleted_at.is_(None),
        )
        .group_by(Photo.entity_type, Photo.entity_id)
        .having(count > MAX_REPORT_PHOTOS)
        .order_by(Photo.entity_type, Photo.entity_id)
    )
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            async for row in await session.stream(query):
                print(
                    json.dumps(
                        {
                            "finding": "active_photo_quota_exceeded",
                            **row._mapping,
                            "maximum_active_photos": MAX_REPORT_PHOTOS,
                            "proposed_disposition": "review_with_records_owner",
                        },
                        default=str,
                    )
                )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-understand", action="store_true")
    args = parser.parse_args()
    if get_settings().app_env.lower() == "production" and not args.i_understand:
        parser.error("Authorized production operators must pass --i-understand.")
    asyncio.run(report_drift())


if __name__ == "__main__":
    main()
