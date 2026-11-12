"""Review or apply an exact audit-retention deadline extension plan."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    model_validator,
)
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.activity_log import ActivityLog
from app.services.audit_retention_policy import (
    AuditRetentionPolicyError,
    Identifier,
    VerifiedAuditRetentionPolicy,
    _unique_json_object,
)
from app.services.audit_service import RETENTION_BATCH_SIZE, AuditService
from app.utils.security import utc_now

_APPLY_BATCH_SIZE = 100
_RECEIPT_ACTION = "maintenance.audit_retention_extension"
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Count = Annotated[StrictInt, Field(ge=0)]


class RetentionPlanError(ValueError):
    """Operator error that can be reported without record payloads."""


class ExtensionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: UUID
    class_id: Identifier
    observed_created_at: AwareDatetime
    observed_deadline: AwareDatetime | None
    observed_policy_version: None = None
    proposed_deadline: AwareDatetime
    reason: Literal["missing_retention_deadline", "policy_extends_deadline"]

    @model_validator(mode="after")
    def extends_protection(self) -> ExtensionEntry:
        if self.observed_deadline is None:
            if self.reason != "missing_retention_deadline":
                raise ValueError("A missing deadline requires the corresponding reason.")
        elif (
            self.proposed_deadline <= self.observed_deadline
            or self.reason != "policy_extends_deadline"
        ):
            raise ValueError("An extension must increase an existing deadline.")
        return self


class ExtensionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1]
    policy_id: Identifier
    policy_revision: Identifier
    policy_sha256: Digest
    target_sha256: Digest
    inspected_at_utc: AwareDatetime
    inspected_count: Count
    protected_unknown_count: Count
    unchanged_count: Count
    extension_count: Count
    entries: tuple[ExtensionEntry, ...]

    @model_validator(mode="after")
    def complete_and_ordered(self) -> ExtensionPlan:
        ids = [entry.record_id for entry in self.entries]
        if ids != sorted(set(ids)):
            raise ValueError("Plan entries must be ordered by unique record ID.")
        if self.extension_count != len(ids) or self.inspected_count != (
            self.extension_count + self.protected_unknown_count + self.unchanged_count
        ):
            raise ValueError("Plan totals do not match the inspected population.")
        if any(entry.observed_created_at > self.inspected_at_utc for entry in self.entries):
            raise ValueError("A record was created after the recorded inspection cutoff.")
        return self


def target_fingerprint() -> str:
    settings = get_settings()
    url = make_url(settings.database_url)
    identity = [settings.app_env.lower(), url.host, url.port or 5432, url.database]
    return sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


async def build_extension_plan(
    session: AsyncSession, verified: VerifiedAuditRetentionPolicy, cutoff: datetime
) -> ExtensionPlan:
    query = (
        select(
            ActivityLog.id,
            ActivityLog.event_type,
            ActivityLog.action,
            ActivityLog.created_at,
            ActivityLog.retention_until,
        )
        .where(ActivityLog.deleted_at.is_(None), ActivityLog.created_at <= cutoff)
        .order_by(ActivityLog.id)
        .limit(RETENTION_BATCH_SIZE)
    )
    after = None
    unknown = 0
    unchanged = 0
    entries: list[ExtensionEntry] = []
    while True:
        page = (
            await session.execute(query if after is None else query.where(ActivityLog.id > after))
        ).all()
        if not page:
            break
        for row in page:
            rule = verified.policy.classify(row.action, row.event_type)
            if rule is None:
                unknown += 1
                continue
            deadline = rule.deadline(row.created_at)
            if row.retention_until is not None and row.retention_until >= deadline:
                unchanged += 1
                continue
            entries.append(
                ExtensionEntry(
                    record_id=row.id,
                    class_id=rule.class_id,
                    observed_created_at=row.created_at,
                    observed_deadline=row.retention_until,
                    proposed_deadline=deadline,
                    reason="missing_retention_deadline"
                    if row.retention_until is None
                    else "policy_extends_deadline",
                )
            )
        after = page[-1].id
    return ExtensionPlan(
        format_version=1,
        policy_id=verified.policy.policy_id,
        policy_revision=verified.policy.revision,
        policy_sha256=verified.sha256,
        target_sha256=target_fingerprint(),
        inspected_at_utc=cutoff,
        inspected_count=unknown + unchanged + len(entries),
        protected_unknown_count=unknown,
        unchanged_count=unchanged,
        extension_count=len(entries),
        entries=tuple(entries),
    )


def write_extension_plan(path: Path, plan: ExtensionPlan) -> str:
    content = plan.model_dump_json(indent=2).encode()
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
        output.write(content)
    return sha256(content).hexdigest()


def read_extension_plan(path: Path, expected_digest: str | None) -> tuple[ExtensionPlan, str]:
    content = path.read_bytes()
    digest = sha256(content).hexdigest()
    if expected_digest is not None and not hmac.compare_digest(digest, expected_digest):
        raise RetentionPlanError("The plan SHA-256 does not match the approved digest.")
    try:
        plan = ExtensionPlan.model_validate(
            json.loads(content, object_pairs_hook=_unique_json_object)
        )
    except (ValueError, RecursionError):
        raise RetentionPlanError("The plan format or totals are invalid.") from None
    return plan, digest


async def execute_batch(
    session: AsyncSession,
    plan: ExtensionPlan,
    digest: str,
    batch_number: int,
    entries: Sequence[ExtensionEntry],
    *,
    approval_reference: str | None,
) -> Literal["ready", "applied", "already_applied"]:
    audit = AuditService(session)
    verified = audit.configured_retention_policy()
    if (
        verified is None
        or (verified.sha256, verified.policy.policy_id, verified.policy.revision)
        != (plan.policy_sha256, plan.policy_id, plan.policy_revision)
        or target_fingerprint() != plan.target_sha256
        or plan.inspected_at_utc > utc_now()
    ):
        raise RetentionPlanError(
            "The active policy, target, or inspection time does not match the plan."
        )

    if not entries:
        return "ready"

    if approval_reference is not None:
        # A shared transaction lock prevents concurrent retries from duplicating the receipt.
        key = int.from_bytes(bytes.fromhex(digest[:16]), "big", signed=True)
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    prior = await session.scalar(
        select(ActivityLog.id)
        .where(
            ActivityLog.action == _RECEIPT_ACTION,
            ActivityLog.context_payload["plan_sha256"].as_string() == digest,
            ActivityLog.context_payload["batch_number"].as_integer() == batch_number,
            ActivityLog.context_payload["record_count"].as_integer() == len(entries),
            ActivityLog.deleted_at.is_(None),
        )
        .limit(1)
    )
    if prior is not None:
        return "already_applied"

    query = (
        select(ActivityLog)
        .where(
            ActivityLog.id.in_([entry.record_id for entry in entries]),
            ActivityLog.deleted_at.is_(None),
        )
        .order_by(ActivityLog.id)
    )
    if approval_reference is not None:
        query = query.with_for_update()
    rows = (await session.scalars(query)).all()
    if len(rows) != len(entries):
        raise RetentionPlanError(f"Batch {batch_number} is stale because a record is missing.")
    for row, entry in zip(rows, entries, strict=True):
        rule = verified.policy.classify(row.action, row.event_type)
        if (
            row.id != entry.record_id
            or row.created_at != entry.observed_created_at
            or row.retention_until != entry.observed_deadline
            or rule is None
            or rule.class_id != entry.class_id
            or rule.deadline(row.created_at) != entry.proposed_deadline
        ):
            raise RetentionPlanError(f"Batch {batch_number} is stale or does not match policy.")

    if approval_reference is None:
        return "ready"
    for row, entry in zip(rows, entries, strict=True):
        row.retention_until = entry.proposed_deadline
    await audit.record(
        action=_RECEIPT_ACTION,
        event_type="system_event",
        entity_type="log_events",
        context_payload={
            "plan_sha256": digest,
            "policy_sha256": verified.sha256,
            "batch_number": batch_number,
            "record_count": len(entries),
            "approval_reference_sha256": sha256(approval_reference.encode()).hexdigest(),
        },
    )
    return "applied"


async def execute_plan(plan: ExtensionPlan, digest: str, *, approval_reference: str | None) -> None:
    # Check the configured policy even for an empty plan.
    batches = [
        plan.entries[start : start + _APPLY_BATCH_SIZE]
        for start in range(0, len(plan.entries), _APPLY_BATCH_SIZE)
    ] or [()]
    try:
        for number, entries in enumerate(batches, start=1):
            async with AsyncSessionLocal() as session, session.begin():
                if approval_reference is None:
                    await session.execute(
                        text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    )
                outcome = await execute_batch(
                    session, plan, digest, number, entries, approval_reference=approval_reference
                )
            print(
                json.dumps({"batch_number": number, "count": len(entries), "status": outcome}),
                flush=True,
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--authorization-ref", help="Reference to separate approval for this plan.")
    parser.add_argument(
        "--apply", action="store_true", help="Write an approved plan in bounded batches."
    )
    parser.add_argument("--i-understand", action="store_true")
    args = parser.parse_args()
    if get_settings().app_env.lower() in {"prod", "production"} and not args.i_understand:
        parser.error("Authorized production operators must pass --i-understand.")
    if args.apply and (
        not args.plan_sha256 or not args.authorization_ref or not args.authorization_ref.strip()
    ):
        parser.error("--apply requires the exact --plan-sha256 and a separate --authorization-ref.")
    try:
        plan, digest = read_extension_plan(args.plan, args.plan_sha256)
        asyncio.run(
            execute_plan(
                plan, digest, approval_reference=args.authorization_ref if args.apply else None
            )
        )
    except (RetentionPlanError, AuditRetentionPolicyError) as error:
        parser.exit(1, f"{error}\n")
    except Exception as error:
        parser.exit(
            1,
            f"Retention operation failed ({type(error).__name__}). Review prior batch receipts.\n",
        )


if __name__ == "__main__":
    main()
