"""Preview audit retention deadlines without modifying event records."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.activity_log import ActivityLog
from app.services.audit_retention_policy import (
    AuditRetentionPolicyError,
    VerifiedAuditRetentionPolicy,
)
from app.services.audit_service import AuditService
from app.utils.security import utc_now
from scripts.apply_audit_retention import (
    RetentionPlanError,
    build_extension_plan,
    write_extension_plan,
)

_CATEGORY_REASONS = {
    "missing": "missing_retention_deadline",
    "held": "approved_hold",
    "future": "deadline_in_future",
    "unknown": "unclassified_retained_for_review",
    "shorter_than_policy": "deadline_shorter_than_policy",
    "eligible": "classified_archived_expired",
}


async def category_page(
    audit: AuditService,
    policy: VerifiedAuditRetentionPolicy | None,
    cutoff: datetime,
    category: str,
    *,
    limit: int,
    after: UUID | None,
) -> tuple[list[dict], str | None]:
    condition = audit.retention_categories(policy, cutoff)[category]
    query = (
        select(
            ActivityLog.id,
            ActivityLog.created_at,
            ActivityLog.storage_tier,
            ActivityLog.retention_until,
        )
        .where(ActivityLog.deleted_at.is_(None), ActivityLog.created_at <= cutoff, condition)
        .order_by(ActivityLog.id)
        .limit(limit + 1)
    )
    if after is not None:
        query = query.where(ActivityLog.id > after)
    rows = (await audit.session.execute(query)).all()
    page = [
        {
            "id": str(row.id),
            "created_at": row.created_at.isoformat(),
            "storage_tier": row.storage_tier,
            "retention_until": row.retention_until.isoformat() if row.retention_until else None,
            "reason": _CATEGORY_REASONS[category],
        }
        for row in rows[:limit]
    ]
    next_after = page[-1]["id"] if len(rows) > limit else None
    return page, next_after


async def preview(
    *,
    category: str = "missing",
    limit: int = 100,
    after: UUID | None = None,
    cutoff: datetime | None = None,
    extension_plan_path: Path | None = None,
) -> None:
    captured_cutoff = cutoff or utc_now()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            audit = AuditService(session)
            verified = audit.configured_retention_policy()
            mode = verified.policy.mode if verified else "unconfigured"
            counts = await audit.retention_counts(verified, captured_cutoff)
            page, next_after = await category_page(
                audit, verified, captured_cutoff, category, limit=limit, after=after
            )
            candidates = await audit.preview_purge(cutoff_at=captured_cutoff)
            payload = {
                "cutoff_utc": captured_cutoff.isoformat(),
                "policy_revision": verified.policy.revision if verified else None,
                "policy_sha256": verified.sha256 if verified else None,
                "mode": mode,
                "holds_supported": False,
                "archive_retention_days": audit.settings.log_archive_retention_days,
                "purge_requested": audit.settings.log_purge_enabled,
                "purge_enabled": audit.settings.log_purge_enabled and mode == "scheduled_expiry",
                "counts": counts,
                "category": category,
                "rows": page,
                "next_after": next_after,
                "missing_deadlines": counts["missing"],
                "missing_deadline_batch": [
                    {**row, "proposed_disposition": "retain_pending_owner_review"} for row in page
                ]
                if category == "missing"
                else [],
                "next_missing_after": next_after if category == "missing" else None,
                "candidate_batch": [
                    {"id": str(event_id), "retention_until": deadline.isoformat()}
                    for event_id, deadline in candidates
                ],
                "candidate_batch_has_more": counts["eligible"] > len(candidates),
            }
            if extension_plan_path is not None:
                if verified is None:
                    raise RetentionPlanError("A verified policy is required to propose extensions.")
                plan = await build_extension_plan(session, verified, captured_cutoff)
                payload["extension_plan"] = {
                    "sha256": write_extension_plan(extension_plan_path, plan),
                    "extensions": plan.extension_count,
                    "protected_unknown": plan.protected_unknown_count,
                }
            print(json.dumps(payload))
    finally:
        await engine.dispose()


def utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("missing time zone")
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        raise argparse.ArgumentTypeError(
            "Provide an ISO-8601 timestamp with a time zone."
        ) from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-understand", action="store_true")
    parser.add_argument("--category", choices=tuple(_CATEGORY_REASONS), default="missing")
    parser.add_argument(
        "--limit", "--missing-limit", type=int, default=100, help="Rows per page (1–1000)."
    )
    parser.add_argument(
        "--after", "--missing-after", type=UUID, help="Continue after a prior page cursor."
    )
    parser.add_argument(
        "--cutoff", type=utc_timestamp, help="Reuse the cutoff from a prior preview page."
    )
    parser.add_argument(
        "--extension-plan", type=Path, help="Write a new read-only deadline extension plan."
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000.")
    if args.after is not None and args.cutoff is None and args.category != "missing":
        parser.error("Paginated previews require the original --cutoff.")
    if args.cutoff is not None and args.cutoff > utc_now():
        parser.error("--cutoff cannot be in the future.")
    if get_settings().app_env.lower() in {"prod", "production"} and not args.i_understand:
        parser.error("Authorized production operators must pass --i-understand.")
    try:
        asyncio.run(
            preview(
                category=args.category,
                limit=args.limit,
                after=args.after,
                cutoff=args.cutoff,
                extension_plan_path=args.extension_plan,
            )
        )
    except (AuditRetentionPolicyError, RetentionPlanError) as error:
        parser.exit(1, f"{error}\n")
    except Exception as error:
        parser.exit(1, f"Retention preview failed ({type(error).__name__}).\n")


if __name__ == "__main__":
    main()
