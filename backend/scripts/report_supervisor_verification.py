"""List unresolved historical supervisor verification bindings for review."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine

QUERY = text("""
    SELECT u.id AS update_id, count(r.id) AS candidate_count,
           CASE count(r.id)
             WHEN 0 THEN 'no_historical_candidate'
             WHEN 1 THEN 'unique_candidate_unbound'
             ELSE 'multiple_historical_candidates'
           END AS reason,
           'operator_review' AS proposed_disposition
    FROM supervisor_updates AS u
    LEFT JOIN daily_reports AS r
      ON r.project_id = u.project_id
     AND r.engineer_id = u.verified_by
     AND r.submitted_at >= u.verified_at
     AND r.deleted_at IS NULL
     AND r.supervisor_update_ids @> jsonb_build_array(u.id::text)
    WHERE u.status = 'verified' AND u.deleted_at IS NULL AND u.verified_report_id IS NULL
    GROUP BY u.id
    ORDER BY u.id
    """)


async def report() -> None:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            async for row in await session.stream(QUERY):
                print(json.dumps(dict(row._mapping), default=str))
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
