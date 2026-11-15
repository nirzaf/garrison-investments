"""Validate or apply the reviewed, one-time new-role-only account cutover.

The default operation is read-only. Keep manifests and exported templates in a
restricted operator location; they contain account UUIDs and role mappings.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.approval import Approval
from app.models.import_batch import ImportBatch
from app.models.task_outbox import TaskOutbox
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.utils.permissions import COMPANY_RESOURCE_ROLES, VALID_ROLES
from app.utils.security import utc_now

MAX_MANIFEST_BYTES = 10 * 1024 * 1024
MIGRATION_ACTION = "users.role_catalogue_migration_applied"
MIGRATION_ENTITY = "role_catalogue_migration"
REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,159}$")


class MigrationInputError(ValueError):
    """A manifest or operator invocation failed a safety check."""


@dataclass(frozen=True)
class RoleMapping:
    user_id: UUID
    expected_role: str
    expected_updated_at: datetime
    expected_access_revision: int
    expected_is_active: bool
    expected_deleted_at: datetime | None
    target_role: str
    identity_evidence_reference: str
    decision_reference: str


@dataclass(frozen=True)
class RoleManifest:
    digest: str
    operator_reference: str
    authorization_reference: str
    maintenance_window_reference: str
    mappings: tuple[RoleMapping, ...]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MigrationInputError("The manifest contains a duplicate JSON field.")
        result[key] = value
    return result


def _required_reference(value: Any, label: str) -> str:
    if not isinstance(value, str) or not REFERENCE_PATTERN.fullmatch(value):
        raise MigrationInputError(f"{label} must be a nonempty restricted evidence reference.")
    return value


def _parse_datetime(value: Any, label: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise MigrationInputError(f"{label} must be an ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MigrationInputError(f"{label} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MigrationInputError(f"{label} must include a timezone.")
    return parsed.astimezone(UTC)


def parse_manifest(raw: bytes) -> RoleManifest:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise MigrationInputError("The role manifest exceeds the allowed size.")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MigrationInputError("The role manifest is not valid UTF-8 JSON.") from exc
    if not isinstance(data, dict) or data.get("format_version") != 1:
        raise MigrationInputError("The role manifest format is unsupported.")
    operator_ref = _required_reference(data.get("operator_reference"), "operator_reference")
    auth_ref = _required_reference(data.get("authorization_reference"), "authorization_reference")
    window_ref = _required_reference(
        data.get("maintenance_window_reference"), "maintenance_window_reference"
    )
    rows = data.get("users")
    if not isinstance(rows, list) or not rows:
        raise MigrationInputError("The role manifest must contain at least one user mapping.")

    mappings: list[RoleMapping] = []
    seen: set[UUID] = set()
    for index, row in enumerate(rows):
        label = f"users[{index}]"
        if not isinstance(row, dict):
            raise MigrationInputError(f"{label} must be an object.")
        try:
            user_id = UUID(str(row.get("id")))
        except (ValueError, TypeError, AttributeError) as exc:
            raise MigrationInputError(f"{label}.id must be a UUID.") from exc
        if user_id in seen:
            raise MigrationInputError("The role manifest contains duplicate user UUIDs.")
        seen.add(user_id)
        expected_role = row.get("expected_role")
        if not isinstance(expected_role, str) or not expected_role:
            raise MigrationInputError(f"{label}.expected_role must be an exact stored role key.")
        target_role = row.get("target_role")
        if not isinstance(target_role, str) or target_role not in VALID_ROLES:
            raise MigrationInputError(f"{label}.target_role is not a supported target role.")
        access_revision = row.get("expected_access_revision")
        if type(access_revision) is not int or access_revision < 0:
            raise MigrationInputError(f"{label}.expected_access_revision must be nonnegative.")
        active = row.get("expected_is_active")
        if type(active) is not bool:
            raise MigrationInputError(f"{label}.expected_is_active must be boolean.")
        deleted_at = _parse_datetime(
            row.get("expected_deleted_at"), f"{label}.expected_deleted_at", nullable=True
        )
        expected_updated_at = _parse_datetime(
            row.get("expected_updated_at"), f"{label}.expected_updated_at"
        )
        assert expected_updated_at is not None
        mappings.append(
            RoleMapping(
                user_id=user_id,
                expected_role=expected_role,
                expected_updated_at=expected_updated_at,
                expected_access_revision=access_revision,
                expected_is_active=active,
                expected_deleted_at=deleted_at,
                target_role=target_role,
                identity_evidence_reference=_required_reference(
                    row.get("identity_evidence_reference"),
                    f"{label}.identity_evidence_reference",
                ),
                decision_reference=_required_reference(
                    row.get("decision_reference"), f"{label}.decision_reference"
                ),
            )
        )
    return RoleManifest(
        digest=hashlib.sha256(raw).hexdigest(),
        operator_reference=operator_ref,
        authorization_reference=auth_ref,
        maintenance_window_reference=window_ref,
        mappings=tuple(mappings),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MigrationInputError("A database timestamp is missing its timezone.")
    return value.astimezone(UTC)


def _matches(mapping: RoleMapping, user: User) -> bool:
    return (
        user.role == mapping.expected_role
        and _as_utc(user.updated_at) == mapping.expected_updated_at
        and user.access_revision == mapping.expected_access_revision
        and user.is_active is mapping.expected_is_active
        and (_as_utc(user.deleted_at) if user.deleted_at is not None else None)
        == mapping.expected_deleted_at
    )


def _is_usable_director(user: User, role: str) -> bool:
    return (
        role in COMPANY_RESOURCE_ROLES
        and user.is_active
        and user.deleted_at is None
        and bool(user.password_hash)
        and (user.locked_until is None or _as_utc(user.locked_until) <= datetime.now(UTC))
    )


def validate_snapshot(users: list[User], manifest: RoleManifest) -> dict[str, Any]:
    by_id = {user.id: user for user in users}
    mappings = {mapping.user_id: mapping for mapping in manifest.mappings}
    missing = set(by_id) - set(mappings)
    unknown = set(mappings) - set(by_id)
    if missing or unknown:
        raise MigrationInputError(
            "Manifest coverage differs from the database account inventory "
            f"(unmapped={len(missing)}, absent={len(unknown)})."
        )
    for mapping in manifest.mappings:
        if not _matches(mapping, by_id[mapping.user_id]):
            raise MigrationInputError("A user row no longer matches its manifest preconditions.")
    directors = [
        user
        for mapping in manifest.mappings
        if _is_usable_director(user := by_id[mapping.user_id], mapping.target_role)
    ]
    if not directors:
        raise MigrationInputError("The proposed cutover leaves no usable MD or OD account.")
    return {
        "account_count": len(users),
        "role_changes": sum(
            by_id[mapping.user_id].role != mapping.target_role for mapping in manifest.mappings
        ),
        "session_revocations": len(users),
        "target_role_counts": dict(
            sorted(Counter(mapping.target_role for mapping in manifest.mappings).items())
        ),
        "usable_directors": len(directors),
    }


def validate_current_catalogue(users: list[User]) -> dict[str, Any]:
    """Fail closed unless a rehearsed database already uses only target roles."""
    unsupported = sum(user.role not in VALID_ROLES for user in users)
    usable_directors = sum(
        _is_usable_director(user, user.role) for user in users if user.role in VALID_ROLES
    )
    if unsupported:
        raise MigrationInputError("The current database contains unsupported stored role values.")
    if usable_directors == 0:
        raise MigrationInputError("The current database has no usable MD or OD account.")
    return {
        "account_count": len(users),
        "unsupported_role_count": 0,
        "usable_directors": usable_directors,
        "outcome": "current_catalogue_valid",
    }


def _check_private_file(path: Path) -> bytes:
    try:
        info = path.stat()
        raw = path.read_bytes()
    except OSError as exc:
        raise MigrationInputError("The manifest file could not be read.") from exc
    if not stat.S_ISREG(info.st_mode):
        raise MigrationInputError("The manifest path must be a regular file.")
    if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
        raise MigrationInputError("The manifest must not be accessible by group or other users.")
    return raw


async def _load_all_users(session: AsyncSession, *, lock: bool) -> list[User]:
    query = select(User).order_by(User.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list((await session.scalars(query)).all())


async def export_template(path: Path) -> None:
    if path.exists():
        raise MigrationInputError("Refusing to overwrite an existing manifest template.")
    async with AsyncSessionLocal() as session:
        users = await _load_all_users(session, lock=False)
    rows = [
        {
            "id": str(user.id),
            "expected_role": user.role,
            "expected_updated_at": _as_utc(user.updated_at).isoformat().replace("+00:00", "Z"),
            "expected_access_revision": user.access_revision,
            "expected_is_active": user.is_active,
            "expected_deleted_at": (
                _as_utc(user.deleted_at).isoformat().replace("+00:00", "Z")
                if user.deleted_at is not None
                else None
            ),
            "target_role": None,
            "identity_evidence_reference": None,
            "decision_reference": None,
        }
        for user in users
    ]
    document = {
        "format_version": 1,
        "operator_reference": None,
        "authorization_reference": None,
        "maintenance_window_reference": None,
        "users": rows,
    }
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(document, output, indent=2)
            output.write("\n")
    except OSError as exc:
        raise MigrationInputError("The restricted manifest template could not be written.") from exc
    print(json.dumps({"template_created": True, "account_count": len(rows), "path": str(path)}))


async def apply_manifest(manifest: RoleManifest, confirmed_digest: str) -> dict[str, Any]:
    if confirmed_digest != manifest.digest:
        raise MigrationInputError("The confirmation digest does not match the manifest bytes.")
    async with AsyncSessionLocal() as session, session.begin():
        await UserRepository(session).lock_access_management()
        users = await _load_all_users(session, lock=True)
        previous_receipts = list(
            await session.scalars(
                select(ActivityLog).where(
                    ActivityLog.action == MIGRATION_ACTION,
                    ActivityLog.entity_type == MIGRATION_ENTITY,
                    ActivityLog.deleted_at.is_(None),
                )
            )
        )
        matching_receipt = next(
            (
                item
                for item in previous_receipts
                if (item.new_values or {}).get("manifest_sha256") == manifest.digest
            ),
            None,
        )
        summary = {
            "manifest_sha256": manifest.digest,
            "account_count": len(users),
        }
        if matching_receipt:
            targets = {mapping.user_id: mapping.target_role for mapping in manifest.mappings}
            if set(targets) != {user.id for user in users} or any(
                user.role != targets[user.id] for user in users
            ):
                raise MigrationInputError(
                    "The prior migration receipt no longer matches account roles."
                )
            return {**summary, "outcome": "already_applied_noop"}
        if previous_receipts:
            raise MigrationInputError(
                "A different role migration receipt already exists; stop for review."
            )
        counts = validate_snapshot(users, manifest)
        mapping_by_id = {mapping.user_id: mapping for mapping in manifest.mappings}
        auth = AuthRepository(session)
        audit = AuditService(session)
        now = utc_now()
        for user in users:
            mapping = mapping_by_id[user.id]
            old_role = user.role
            old_revision = user.access_revision
            user.role = mapping.target_role
            # Revoke every account's credentials because the authorization policy
            # is replaced atomically, even when its role key happens to be unchanged.
            user.access_revision += 1
            user.updated_at = now
            await auth.revoke_user_authentication(user.id)
            await audit.record(
                action="users.role_catalogue_account_migrated",
                user_id=None,
                entity_type="users",
                entity_id=user.id,
                comments="Account role updated by the approved new-role-only cutover.",
                context_payload={
                    "manifest_sha256": manifest.digest,
                    "operator_reference": manifest.operator_reference,
                    "authorization_reference": manifest.authorization_reference,
                    "maintenance_window_reference": manifest.maintenance_window_reference,
                    "identity_evidence_reference": mapping.identity_evidence_reference,
                    "decision_reference": mapping.decision_reference,
                },
                old_values={"role": old_role, "access_revision": old_revision},
                new_values={"role": user.role, "access_revision": user.access_revision},
            )
        # Validate the final in-memory account set before adding the terminal receipt.
        for user in users:
            if user.role not in VALID_ROLES:
                raise MigrationInputError(
                    "A target account role is not in the supported catalogue."
                )
        if not any(_is_usable_director(user, user.role) for user in users):
            raise MigrationInputError("The applied changes leave no usable MD or OD account.")
        await audit.record(
            action=MIGRATION_ACTION,
            user_id=None,
            entity_type=MIGRATION_ENTITY,
            comments="One-time new-role-only account cutover completed.",
            context_payload={
                "operator_reference": manifest.operator_reference,
                "authorization_reference": manifest.authorization_reference,
                "maintenance_window_reference": manifest.maintenance_window_reference,
            },
            new_values={
                "manifest_sha256": manifest.digest,
                **counts,
            },
        )
        return {**summary, **counts, "outcome": "applied"}


async def validate_read_only(manifest: RoleManifest) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        users = await _load_all_users(session, lock=False)
        return {
            "manifest_sha256": manifest.digest,
            **validate_snapshot(users, manifest),
            "outcome": "dry_run_valid",
        }


async def verify_current_read_only() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        users = await _load_all_users(session, lock=False)
        return validate_current_catalogue(users)


async def inspect_pending_workflows() -> dict[str, Any]:
    """Return sanitized counts for operator-led pending-work reconciliation."""
    async with AsyncSessionLocal() as session:
        approval_rows = await session.execute(
            select(Approval.request_type, Approval.status, func.count())
            .where(Approval.deleted_at.is_(None))
            .group_by(Approval.request_type, Approval.status)
            .order_by(Approval.request_type, Approval.status)
        )
        import_rows = await session.execute(
            select(ImportBatch.template_type, ImportBatch.status, func.count())
            .where(ImportBatch.deleted_at.is_(None))
            .group_by(ImportBatch.template_type, ImportBatch.status)
            .order_by(ImportBatch.template_type, ImportBatch.status)
        )
        outbox_rows = await session.execute(
            select(TaskOutbox.task_name, TaskOutbox.status, func.count())
            .group_by(TaskOutbox.task_name, TaskOutbox.status)
            .order_by(TaskOutbox.task_name, TaskOutbox.status)
        )

    def counts(rows: Any, first: str, second: str) -> list[dict[str, Any]]:
        return [
            {first: value_a, second: value_b, "count": count}
            for value_a, value_b, count in rows
        ]

    return {
        "approvals": counts(approval_rows, "request_type", "status"),
        "import_batches": counts(import_rows, "template_type", "status"),
        "task_outbox": counts(outbox_rows, "task_name", "status"),
        "outcome": "sanitized_workflow_counts",
        "write_performed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--manifest", type=Path)
    group.add_argument("--export-template", type=Path)
    group.add_argument(
        "--verify-current",
        action="store_true",
        help="Check that the database already contains only supported roles and a usable director.",
    )
    group.add_argument(
        "--inspect-pending-workflows",
        action="store_true",
        help="Print sanitized approval, import-batch, and task-outbox counts for reconciliation.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply the validated mapping.")
    parser.add_argument("--confirm-manifest-sha256")
    args = parser.parse_args(argv)
    try:
        if args.verify_current:
            if args.apply or args.confirm_manifest_sha256:
                raise MigrationInputError("Current-catalogue verification is read-only.")
            result = asyncio.run(verify_current_read_only())
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.inspect_pending_workflows:
            if args.apply or args.confirm_manifest_sha256:
                raise MigrationInputError("Workflow inspection is read-only.")
            result = asyncio.run(inspect_pending_workflows())
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.export_template:
            if args.apply or args.confirm_manifest_sha256:
                raise MigrationInputError("Template export cannot be combined with apply options.")
            asyncio.run(export_template(args.export_template))
            return 0
        raw = _check_private_file(args.manifest)
        manifest = parse_manifest(raw)
        if args.apply:
            if not args.confirm_manifest_sha256:
                raise MigrationInputError("Apply requires --confirm-manifest-sha256.")
            result = asyncio.run(apply_manifest(manifest, args.confirm_manifest_sha256))
        else:
            if args.confirm_manifest_sha256:
                raise MigrationInputError("A digest confirmation is valid only with --apply.")
            result = asyncio.run(validate_read_only(manifest))
        print(json.dumps(result, sort_keys=True))
        return 0
    except MigrationInputError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:
        # Database errors can include connection details; keep terminal receipts safe.
        print(
            json.dumps({"error": "Role catalogue operation failed.", "type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
