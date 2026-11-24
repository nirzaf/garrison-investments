"""Report material requests and site attendance missing staged submission evidence."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine

MATERIAL_REQUESTS = text("""
    SELECT r.id, r.project_id, r.status, r.revision, r.submission_revision,
           COALESCE(SUM(l.quantity), 0) AS requested_quantity,
           COALESCE(SUM(l.reserved_quantity), 0) AS reserved_quantity,
           COALESCE(SUM(l.issued_quantity), 0) AS issued_quantity,
           'engineer_and_gpm_submission_decisions' AS missing_evidence,
           CASE
               WHEN r.status IN ('issued', 'cancelled') THEN 'historical_only'
               WHEN COALESCE(SUM(l.reserved_quantity), 0) > 0
                   THEN 'requires_reservation_release'
               WHEN COALESCE(SUM(l.issued_quantity), 0) > 0 THEN 'manual_reconciliation'
               WHEN r.status IN ('approved', 'requested') THEN 'eligible_for_resubmission'
               ELSE 'manual_reconciliation'
           END AS disposition
    FROM material_requests r
    LEFT JOIN material_request_lines l ON l.request_id = r.id AND l.deleted_at IS NULL
    WHERE r.deleted_at IS NULL AND r.submission_revision IS NULL AND r.status <> 'draft'
    GROUP BY r.id
    ORDER BY r.id
""")

SITE_ATTENDANCE = text("""
    SELECT a.id, a.employee_id, a.project_id, a.status, a.record_revision AS revision,
           a.work_date, a.worked_hours, a.site_submission_revision,
           'current_engineer_and_hr_decisions' AS missing_evidence,
           CASE WHEN a.status IN ('approved', 'historical') THEN 'historical_only'
                ELSE 'manual_reconciliation' END AS disposition
    FROM hr_attendance_entries a
    WHERE a.project_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM hr_site_attendance_submissions s
        WHERE s.entry_id = a.id AND s.submission_revision = a.site_submission_revision
          AND s.engineer_decision = 'approved' AND s.hr_decision = 'approved'
    )
      AND a.site_submission_revision IS NULL
    ORDER BY a.id
""")


async def report() -> None:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            for category, query in (
                ("legacy_material_request", MATERIAL_REQUESTS),
                ("legacy_site_attendance", SITE_ATTENDANCE),
            ):
                async for row in await session.stream(query):
                    print(json.dumps({"finding": category, **row._mapping}, default=str))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-understand", action="store_true")
    args = parser.parse_args()
    if get_settings().app_env.lower() == "production" and not args.i_understand:
        parser.error("Authorized production operators must pass --i-understand.")
    asyncio.run(report())


if __name__ == "__main__":
    main()
