"""Trusted verification and append-only ingestion of signed backup and restore receipts."""

from __future__ import annotations

import hmac
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_oversight import SupportBackupReceipt
from app.utils.security import utc_now
from scripts.backup_set_contract import (
    LOOPBACK,
    BackupSetError,
    RecoveryPolicy,
    RestoreDrillReceipt,
    read_policy,
    verify_publication_receipt,
    verify_restore_drill,
    verify_scheduled_attempt,
)


class BackupReceiptError(Exception):
    pass


async def _lock_receipts(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('garrison.support_backup_receipts'))")
    )


def _validate_policy_scope(policy_path: Path, expected_policy_sha256: str) -> tuple[object, str]:
    try:
        policy, policy_sha = read_policy(policy_path)
    except BackupSetError as exc:
        raise BackupReceiptError(str(exc)) from None
    if not hmac.compare_digest(policy_sha, expected_policy_sha256):
        raise BackupReceiptError("Recovery policy SHA-256 does not match the approved digest.")
    if policy.failure_domains.source == policy.failure_domains.destination:
        raise BackupReceiptError("Independent backup receipts require distinct failure domains.")
    endpoint_host = policy.destination_identity.endpoint.split(":", 1)[0].strip("[]").lower()
    if policy.source_environment != "test" and endpoint_host in LOOPBACK:
        raise BackupReceiptError("Non-test recovery policy cannot target loopback storage.")
    return policy, policy_sha


async def ingest_publication_receipt(
    session: AsyncSession,
    raw_bytes: bytes,
    *,
    policy_path: Path,
    expected_policy_sha256: str,
    key_file: Path,
    key_id: str,
    recorded_by: str = "backup_receipt_ingestion",
) -> tuple[SupportBackupReceipt, bool]:
    policy, policy_sha = _validate_policy_scope(policy_path, expected_policy_sha256)
    try:
        receipt = verify_publication_receipt(raw_bytes, key_file=key_file, key_id=key_id)
    except BackupSetError as exc:
        raise BackupReceiptError(str(exc)) from None
    if (
        receipt.source_environment != policy.source_environment  # type: ignore[attr-defined]
        or receipt.policy_revision != policy.revision  # type: ignore[attr-defined]
        or receipt.policy_sha256 != policy_sha
        or receipt.destination_identity != policy.destination_identity  # type: ignore[attr-defined]
    ):
        raise BackupReceiptError("Publication receipt does not match the approved policy scope.")

    await _lock_receipts(session)
    existing = await session.scalar(
        select(SupportBackupReceipt)
        .where(
            SupportBackupReceipt.receipt_kind == "authenticated_backup_set",
            SupportBackupReceipt.backup_set_id == receipt.backup_set_id,
        )
        .order_by(SupportBackupReceipt.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        if (
            existing.manifest_sha256 == receipt.manifest_sha256
            and existing.signer_key_id == key_id
            and existing.captured_at == receipt.snapshot_at_utc
        ):
            return existing, False
        raise BackupReceiptError("Conflicting backup set receipt already recorded for this set ID.")

    row = SupportBackupReceipt(
        id=uuid4(),
        receipt_kind="authenticated_backup_set",
        backup_set_id=receipt.backup_set_id,
        manifest_sha256=receipt.manifest_sha256,
        target_domain="independent_offhost",
        covers_database="application_database" in policy.required_artifact_categories,  # type: ignore[attr-defined]
        covers_objects="objects" in policy.required_artifact_categories,  # type: ignore[attr-defined]
        outcome="pass",
        rpo_minutes=policy.rpo_minutes,  # type: ignore[attr-defined]
        rto_minutes=None,
        captured_at=receipt.snapshot_at_utc,
        verified_at=receipt.remote_verified_at_utc,
        signer_key_id=key_id,
        recorded_by=recorded_by,
        created_at=utc_now(),
    )
    session.add(row)
    await session.flush()
    return row, True


async def ingest_scheduled_attempt_receipt(
    session: AsyncSession,
    raw_bytes: bytes,
    *,
    policy_path: Path,
    expected_policy_sha256: str,
    key_file: Path,
    key_id: str,
    recorded_by: str = "backup_receipt_ingestion",
) -> tuple[SupportBackupReceipt, bool]:
    policy, policy_sha = _validate_policy_scope(policy_path, expected_policy_sha256)
    try:
        attempt = verify_scheduled_attempt(raw_bytes, key_file=key_file, key_id=key_id)
    except BackupSetError as exc:
        raise BackupReceiptError(str(exc)) from None
    if (
        attempt.source_environment != policy.source_environment  # type: ignore[attr-defined]
        or attempt.policy_revision != policy.revision  # type: ignore[attr-defined]
        or attempt.policy_sha256 != policy_sha
    ):
        raise BackupReceiptError("Scheduled attempt receipt does not match the approved policy.")

    await _lock_receipts(session)
    existing = await session.scalar(
        select(SupportBackupReceipt)
        .where(
            SupportBackupReceipt.receipt_kind == "scheduled_db_attempt",
            SupportBackupReceipt.captured_at == attempt.completed_at_utc,
            SupportBackupReceipt.outcome == attempt.outcome,
            SupportBackupReceipt.signer_key_id == key_id,
            SupportBackupReceipt.recorded_by == recorded_by,
        )
        .limit(1)
    )
    if existing is not None:
        return existing, False

    row = SupportBackupReceipt(
        id=uuid4(),
        receipt_kind="scheduled_db_attempt",
        backup_set_id=None,
        manifest_sha256=None,
        target_domain="independent_offhost",
        covers_database=True,
        covers_objects=False,
        outcome=attempt.outcome,
        rpo_minutes=policy.rpo_minutes,  # type: ignore[attr-defined]
        rto_minutes=None,
        captured_at=attempt.completed_at_utc,
        verified_at=attempt.completed_at_utc if attempt.outcome == "pass" else None,
        signer_key_id=key_id,
        recorded_by=recorded_by,
        created_at=utc_now(),
    )
    session.add(row)
    await session.flush()
    return row, True


def restore_drill_satisfies_policy(drill: RestoreDrillReceipt, policy: RecoveryPolicy) -> bool:
    needs_db = "application_database" in policy.required_artifact_categories
    needs_objects = "objects" in policy.required_artifact_categories
    return (not needs_db or drill.covers_database) and (not needs_objects or drill.covers_objects)


async def ingest_restore_drill_receipt(
    session: AsyncSession,
    raw_bytes: bytes,
    *,
    policy_path: Path,
    expected_policy_sha256: str,
    key_file: Path,
    key_id: str,
    recorded_by: str = "backup_receipt_ingestion",
    require_full_policy_coverage: bool = False,
) -> tuple[SupportBackupReceipt, bool]:
    policy, policy_sha = _validate_policy_scope(policy_path, expected_policy_sha256)
    try:
        drill = verify_restore_drill(raw_bytes, key_file=key_file, key_id=key_id)
    except BackupSetError as exc:
        raise BackupReceiptError(str(exc)) from None
    if (
        drill.source_environment != policy.source_environment  # type: ignore[attr-defined]
        or drill.policy_revision != policy.revision  # type: ignore[attr-defined]
        or drill.policy_sha256 != policy_sha
    ):
        raise BackupReceiptError("Restore drill receipt does not match the approved policy.")
    if (
        require_full_policy_coverage
        and drill.outcome == "pass"
        and not restore_drill_satisfies_policy(drill, policy)  # type: ignore[arg-type]
    ):
        raise BackupReceiptError(
            "Restore drill receipt does not cover all artifact categories "
            "required by recovery policy."
        )

    await _lock_receipts(session)
    existing = await session.scalar(
        select(SupportBackupReceipt)
        .where(
            SupportBackupReceipt.receipt_kind == "restore_drill",
            SupportBackupReceipt.backup_set_id == drill.backup_set_id,
            SupportBackupReceipt.manifest_sha256 == drill.manifest_sha256,
            SupportBackupReceipt.verified_at == drill.verified_at_utc,
            SupportBackupReceipt.signer_key_id == key_id,
        )
        .limit(1)
    )
    if existing is not None:
        if existing.outcome == drill.outcome:
            return existing, False
        raise BackupReceiptError("Conflicting restore drill outcome already recorded.")

    row = SupportBackupReceipt(
        id=uuid4(),
        receipt_kind="restore_drill",
        backup_set_id=drill.backup_set_id,
        manifest_sha256=drill.manifest_sha256,
        target_domain="isolated_restore",
        covers_database=drill.covers_database,
        covers_objects=drill.covers_objects,
        outcome=drill.outcome,
        rpo_minutes=None,
        rto_minutes=drill.rto_minutes,
        captured_at=drill.started_at_utc,
        verified_at=drill.verified_at_utc,
        signer_key_id=key_id,
        recorded_by=recorded_by,
        created_at=utc_now(),
    )
    session.add(row)
    await session.flush()
    return row, True


async def record_local_scheduled_db_attempt(
    session: AsyncSession,
    *,
    outcome: Literal["pass", "fail"],
    captured_at: datetime | None = None,
    recorded_by: str = "celery:run_database_backup",
) -> SupportBackupReceipt:
    now = captured_at or utc_now()
    row = SupportBackupReceipt(
        id=uuid4(),
        receipt_kind="scheduled_db_attempt",
        backup_set_id=None,
        manifest_sha256=None,
        target_domain="local_host",
        covers_database=True,
        covers_objects=False,
        outcome=outcome,
        rpo_minutes=None,
        rto_minutes=None,
        captured_at=now,
        verified_at=None,
        signer_key_id=None,
        recorded_by=recorded_by,
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return row
